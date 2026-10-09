#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>

#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>
#include <nav_msgs/msg/occupancy_grid.hpp>
#include <nav2_msgs/action/navigate_to_pose.hpp>
#include <tf2/exceptions.h>
#include <tf2/time.h>
#include <tf2_ros/buffer.h>
#include <tf2_ros/transform_listener.h>

#include <SFML/Graphics.hpp>

using NavigateToPose = nav2_msgs::action::NavigateToPose;
using GoalHandleNav = rclcpp_action::ClientGoalHandle<NavigateToPose>;

namespace
{
constexpr unsigned kWindowWidth = 800;
constexpr unsigned kWindowHeight = 700;
constexpr float kHintBar = 32.f;

// How the occupancy grid is drawn into the window. Mouse clicks use the same
// numbers, so a click lands on the cell under the cursor.
struct MapLayout
{
  bool valid{false};
  int width{0};
  int height{0};
  double resolution{0.05};
  double origin_x{0.0};
  double origin_y{0.0};
  float scale{1.f};
  float offset_x{0.f};
  float offset_y{0.f};
};

// 0 = free -> white, 100 = occupied -> black, -1 = unknown -> mid gray.
sf::Color cellColor(int8_t value)
{
  if (value < 0) {
    return sf::Color(120, 120, 120);
  }
  int shade = 255 - static_cast<int>((static_cast<double>(value) / 100.0) * 255.0);
  shade = std::max(0, std::min(255, shade));
  return sf::Color(
    static_cast<sf::Uint8>(shade),
    static_cast<sf::Uint8>(shade),
    static_cast<sf::Uint8>(shade));
}

MapLayout layoutFor(
  const nav_msgs::msg::OccupancyGrid & map,
  float view_w,
  float view_h)
{
  MapLayout layout;
  const int width = static_cast<int>(map.info.width);
  const int height = static_cast<int>(map.info.height);
  const double resolution = map.info.resolution;
  const size_t expected =
    static_cast<size_t>(std::max(width, 0)) * static_cast<size_t>(std::max(height, 0));
  if (width <= 0 || height <= 0 || resolution <= 0.0 || map.data.size() < expected) {
    return layout;
  }

  const float avail_h = std::max(1.f, view_h - kHintBar);
  const float scale = std::min(
    view_w / static_cast<float>(width),
    avail_h / static_cast<float>(height));
  if (!(scale > 0.f)) {
    return layout;
  }

  layout.valid = true;
  layout.width = width;
  layout.height = height;
  layout.resolution = resolution;
  layout.origin_x = map.info.origin.position.x;
  layout.origin_y = map.info.origin.position.y;
  layout.scale = scale;
  layout.offset_x = (view_w - static_cast<float>(width) * scale) * 0.5f;
  layout.offset_y = (avail_h - static_cast<float>(height) * scale) * 0.5f;
  return layout;
}

// Image y grows downward; grid y grows upward. ix/iy are in cell units
// from the top-left of the drawn map.
bool imageToWorld(const MapLayout & layout, float mouse_x, float mouse_y, double & wx, double & wy)
{
  if (!layout.valid) {
    return false;
  }
  const float ix = (mouse_x - layout.offset_x) / layout.scale;
  const float iy = (mouse_y - layout.offset_y) / layout.scale;
  if (ix < 0.f || iy < 0.f || ix >= static_cast<float>(layout.width) ||
    iy >= static_cast<float>(layout.height))
  {
    return false;
  }
  wx = layout.origin_x + static_cast<double>(ix) * layout.resolution;
  wy = layout.origin_y + static_cast<double>(layout.height) * layout.resolution -
    static_cast<double>(iy) * layout.resolution;
  return true;
}

void worldToImage(const MapLayout & layout, double wx, double wy, float & ix, float & iy)
{
  ix = static_cast<float>((wx - layout.origin_x) / layout.resolution);
  iy = static_cast<float>(layout.height) -
    static_cast<float>((wy - layout.origin_y) / layout.resolution);
}
}  // namespace

class MapViewerNode : public rclcpp::Node
{
public:
  MapViewerNode()
  : Node("go2_map_viewer")
  {
    // /map is latched (transient_local). A volatile subscriber misses a map
    // that was published before this node started, which is the usual case
    // for map_server and for slam_toolbox between its 5 s updates.
    auto map_qos = rclcpp::QoS(rclcpp::KeepLast(1)).transient_local().reliable();
    map_sub_ = this->create_subscription<nav_msgs::msg::OccupancyGrid>(
      "/map", map_qos,
      [this](const nav_msgs::msg::OccupancyGrid::SharedPtr msg) {
        std::lock_guard<std::mutex> lock(map_mutex_);
        latest_map_ = msg;
      });

    nav_client_ = rclcpp_action::create_client<NavigateToPose>(this, "/navigate_to_pose");

    tf_buffer_ = std::make_shared<tf2_ros::Buffer>(this->get_clock());
    tf_listener_ = std::make_shared<tf2_ros::TransformListener>(*tf_buffer_);

    RCLCPP_INFO(this->get_logger(), "Go2 map viewer started.");
  }

  nav_msgs::msg::OccupancyGrid::SharedPtr getMap()
  {
    std::lock_guard<std::mutex> lock(map_mutex_);
    return latest_map_;
  }

  bool getRobotPose(double & x, double & y)
  {
    try {
      auto t = tf_buffer_->lookupTransform("map", "base_link", tf2::TimePointZero);
      x = t.transform.translation.x;
      y = t.transform.translation.y;
      return true;
    } catch (const tf2::TransformException & ex) {
      RCLCPP_WARN_THROTTLE(
        this->get_logger(), *this->get_clock(), 5000,
        "Could not look up map->base_link: %s", ex.what());
      return false;
    }
  }

  void sendGoal(double x, double y)
  {
    if (!nav_client_->action_server_is_ready()) {
      RCLCPP_WARN(this->get_logger(), "Nav2 action server not available.");
      return;
    }

    uint64_t my_generation;
    {
      std::lock_guard<std::mutex> lock(goal_mutex_);
      // A new goal always supersedes whatever's in flight. Cancel any goal
      // we already have a handle for, and bump the generation so a late
      // response/result for the goal being superseded (handled below,
      // since its handle may not exist yet) can't clobber this one's state.
      if (current_goal_handle_) {
        nav_client_->async_cancel_goal(current_goal_handle_);
        current_goal_handle_.reset();
      }
      my_generation = ++goal_generation_;
      cancel_requested_ = false;
    }

    NavigateToPose::Goal goal_msg;
    goal_msg.pose.header.frame_id = "map";
    goal_msg.pose.header.stamp = this->get_clock()->now();
    goal_msg.pose.pose.position.x = x;
    goal_msg.pose.pose.position.y = y;
    goal_msg.pose.pose.orientation.w = 1.0;

    auto send_goal_options = rclcpp_action::Client<NavigateToPose>::SendGoalOptions();
    send_goal_options.goal_response_callback =
      [this, my_generation](const GoalHandleNav::SharedPtr & handle) {
        std::lock_guard<std::mutex> lock(goal_mutex_);
        if (my_generation != goal_generation_) {
          // A newer goal was sent before this response arrived; this one
          // was already cancelled (or never had a handle to cancel) by
          // sendGoal() above, so just ignore it rather than overwrite the
          // handle for the goal that's actually current.
          return;
        }
        if (!handle) {
          RCLCPP_WARN(this->get_logger(), "Goal was rejected.");
          current_goal_handle_.reset();
          return;
        }
        RCLCPP_INFO(this->get_logger(), "Goal accepted.");
        current_goal_handle_ = handle;
        if (cancel_requested_) {
          // Esc/C was pressed before this goal was even accepted; honor
          // it now instead of silently dropping it.
          RCLCPP_INFO(this->get_logger(), "Cancelling goal that was pending cancellation.");
          nav_client_->async_cancel_goal(handle);
          current_goal_handle_.reset();
          cancel_requested_ = false;
        }
      };
    send_goal_options.result_callback =
      [this, my_generation](const GoalHandleNav::WrappedResult & result) {
        std::lock_guard<std::mutex> lock(goal_mutex_);
        if (my_generation == goal_generation_) {
          current_goal_handle_.reset();
        }
        const char * outcome = "UNKNOWN";
        switch (result.code) {
          case rclcpp_action::ResultCode::SUCCEEDED: outcome = "SUCCEEDED"; break;
          case rclcpp_action::ResultCode::ABORTED: outcome = "ABORTED"; break;
          case rclcpp_action::ResultCode::CANCELED: outcome = "CANCELED"; break;
          default: break;
        }
        RCLCPP_INFO(this->get_logger(), "Navigation result: %s", outcome);
      };

    RCLCPP_INFO(this->get_logger(), "Sending goal: x=%.2f y=%.2f", x, y);
    nav_client_->async_send_goal(goal_msg, send_goal_options);
  }

  void cancelGoal()
  {
    GoalHandleNav::SharedPtr handle;
    {
      std::lock_guard<std::mutex> lock(goal_mutex_);
      handle = current_goal_handle_;
      current_goal_handle_.reset();
      if (!handle) {
        // Nothing accepted yet — either no goal was sent, or one is still
        // waiting on its response callback. Remember the request so it's
        // honored as soon as (if) that goal gets accepted, instead of
        // silently dropping it.
        cancel_requested_ = true;
      }
    }
    if (handle) {
      RCLCPP_INFO(this->get_logger(), "Cancelling navigation goal.");
      nav_client_->async_cancel_goal(handle);
    }
  }

private:
  rclcpp::Subscription<nav_msgs::msg::OccupancyGrid>::SharedPtr map_sub_;
  rclcpp_action::Client<NavigateToPose>::SharedPtr nav_client_;
  std::shared_ptr<tf2_ros::Buffer> tf_buffer_;
  std::shared_ptr<tf2_ros::TransformListener> tf_listener_;

  std::mutex map_mutex_;
  nav_msgs::msg::OccupancyGrid::SharedPtr latest_map_;

  std::mutex goal_mutex_;
  GoalHandleNav::SharedPtr current_goal_handle_;
  uint64_t goal_generation_{0};
  bool cancel_requested_{false};
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<MapViewerNode>();

  std::thread spin_thread([&node]() {rclcpp::spin(node);});
  struct SpinGuard
  {
    std::thread & thread;
    ~SpinGuard()
    {
      if (rclcpp::ok()) {
        rclcpp::shutdown();
      }
      if (thread.joinable()) {
        thread.join();
      }
    }
  } spin_guard{spin_thread};

  sf::RenderWindow window(
    sf::VideoMode(kWindowWidth, kWindowHeight), "Go2 Map Viewer");
  window.setFramerateLimit(30);

  sf::Font font;
  const bool have_font = font.loadFromFile("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf");
  if (!have_font) {
    RCLCPP_WARN(
      node->get_logger(),
      "Could not load DejaVuSans.ttf; the window will not show status text.");
  }

  sf::Texture texture;
  nav_msgs::msg::OccupancyGrid::SharedPtr cached_map;
  MapLayout layout;
  bool texture_ready = false;
  bool warned_bad_map = false;
  bool click_latched = false;

  while (window.isOpen() && rclcpp::ok()) {
    bool clicked = false;
    int click_x = 0;
    int click_y = 0;

    sf::Event event;
    while (window.pollEvent(event)) {
      if (event.type == sf::Event::Closed) {
        window.close();
      } else if (event.type == sf::Event::KeyPressed) {
        if (event.key.code == sf::Keyboard::C || event.key.code == sf::Keyboard::Escape) {
          node->cancelGoal();
        }
      } else if (event.type == sf::Event::MouseButtonReleased) {
        if (event.mouseButton.button == sf::Mouse::Left) {
          click_latched = false;
        }
      } else if (event.type == sf::Event::MouseButtonPressed) {
        // WSLg repeats MouseButtonPressed while the button is held, and each
        // one was becoming another Nav2 goal. One press sends one goal.
        if (event.mouseButton.button == sf::Mouse::Left && !click_latched) {
          click_latched = true;
          clicked = true;
          click_x = event.mouseButton.x;
          click_y = event.mouseButton.y;
        }
      }
    }

    // Mouse events are in window pixels. Drawing uses the view. On this
    // display those two sizes disagree, so a view taken from the resize
    // event put the map outside the pixels on screen while clicks still
    // landed in the layout. Force a 1:1 view of the real window.
    auto map_msg = node->getMap();
    const auto window_size = window.getSize();
    if (window_size.x >= 1 && window_size.y >= 1) {
      window.setView(sf::View(sf::FloatRect(
        0.f, 0.f,
        static_cast<float>(window_size.x),
        static_cast<float>(window_size.y))));
    }
    const float view_w = static_cast<float>(window_size.x);
    const float view_h = static_cast<float>(window_size.y);
    bool current_map_ok = false;
    if (map_msg && view_w >= 1.f && view_h >= 1.f) {
      // Recompute every frame so a resized window picks up a new scale.
      // A bad payload must not replace the last map that actually drew.
      MapLayout candidate = layoutFor(*map_msg, view_w, view_h);
      if (candidate.valid) {
        layout = candidate;
        current_map_ok = true;
        warned_bad_map = false;
      } else {
        if (cached_map) {
          layout = layoutFor(*cached_map, view_w, view_h);
        }
        if (!warned_bad_map) {
          RCLCPP_WARN(
            node->get_logger(),
            "Ignoring occupancy grid: %u x %u cells, resolution %.3f, %zu data values.",
            map_msg->info.width, map_msg->info.height, map_msg->info.resolution,
            map_msg->data.size());
          warned_bad_map = true;
        }
      }
    }

    if (clicked) {
      double wx = 0.0;
      double wy = 0.0;
      if (imageToWorld(layout, static_cast<float>(click_x), static_cast<float>(click_y), wx, wy)) {
        node->sendGoal(wx, wy);
      }
    }

    window.clear(sf::Color(30, 30, 30));

    if (layout.valid) {
      if (current_map_ok && map_msg && map_msg != cached_map) {
        const size_t width = static_cast<size_t>(layout.width);
        const size_t height = static_cast<size_t>(layout.height);
        std::vector<sf::Uint8> pixels(width * height * 4);
        for (size_t y = 0; y < height; ++y) {
          for (size_t x = 0; x < width; ++x) {
            const int8_t value = map_msg->data[y * width + x];
            const sf::Color color = cellColor(value);
            const size_t flipped_y = height - 1 - y;
            const size_t dst = (flipped_y * width + x) * 4;
            pixels[dst] = color.r;
            pixels[dst + 1] = color.g;
            pixels[dst + 2] = color.b;
            pixels[dst + 3] = 255;
          }
        }
        sf::Image image;
        image.create(
          static_cast<unsigned>(width),
          static_cast<unsigned>(height),
          pixels.data());
        texture.loadFromImage(image);
        cached_map = map_msg;
        texture_ready = true;
      }

      if (texture_ready) {
        sf::Sprite sprite(texture);
        sprite.setScale(layout.scale, layout.scale);
        sprite.setPosition(layout.offset_x, layout.offset_y);
        window.draw(sprite);
      }

      double rx = 0.0;
      double ry = 0.0;
      if (node->getRobotPose(rx, ry)) {
        float ix = 0.f;
        float iy = 0.f;
        worldToImage(layout, rx, ry, ix, iy);
        sf::CircleShape robot_marker(6.0f);
        robot_marker.setFillColor(sf::Color::Red);
        robot_marker.setOrigin(6.0f, 6.0f);
        robot_marker.setPosition(
          layout.offset_x + ix * layout.scale,
          layout.offset_y + iy * layout.scale);
        window.draw(robot_marker);
      }
    } else if (have_font) {
      const char * message = map_msg ? "Waiting for a valid map..." : "Waiting for map...";
      sf::Text text(message, font, 20);
      text.setFillColor(sf::Color::White);
      text.setPosition(20.f, 20.f);
      window.draw(text);
    }

    if (have_font) {
      sf::Text hint("Left-click: send Nav2 goal   |   C / Esc: cancel goal", font, 14);
      hint.setFillColor(sf::Color::Yellow);
      hint.setPosition(10.f, static_cast<float>(window_size.y) - 24.f);
      window.draw(hint);
    }

    window.display();
  }

  window.close();
  return 0;
}
