#include "go2_rviz_plugins/keyboard_teleop_panel.hpp"

#include <algorithm>

#include <QFocusEvent>
#include <QKeyEvent>
#include <QLabel>
#include <QVBoxLayout>

namespace go2_rviz_plugins
{

namespace
{
// Same numbers as keyboard_teleop.py, so both tools feel identical.
constexpr double kLinearSpeedDefault = 0.5;
constexpr double kAngularSpeedDefault = 1.5;
constexpr double kLinearSpeedMin = 0.1;
constexpr double kLinearSpeedMax = 1.0;
constexpr double kAngularSpeedMin = 0.3;
constexpr double kAngularSpeedMax = 2.5;
constexpr double kLinearSpeedStep = 0.1;
constexpr double kAngularSpeedStep = 0.3;
constexpr int kPublishRateHz = 10;
}  // namespace

KeyboardTeleopPanel::KeyboardTeleopPanel(QWidget * parent)
: rviz_common::Panel(parent),
  linear_speed_(kLinearSpeedDefault),
  angular_speed_(kAngularSpeedDefault)
{
  status_label_ = new QLabel(this);
  status_label_->setWordWrap(true);
  status_label_->setFrameStyle(QFrame::Panel | QFrame::Sunken);
  status_label_->setAlignment(Qt::AlignTop | Qt::AlignLeft);
  status_label_->setMinimumHeight(140);

  auto * layout = new QVBoxLayout(this);
  layout->addWidget(status_label_, /*stretch=*/1);
  setLayout(layout);

  // This panel (not a child widget) is the key-capture target: it must be
  // focused (click it) for key presses to reach keyPressEvent below rather
  // than going to RViz's own views/shortcuts.
  setFocusPolicy(Qt::StrongFocus);

  node_ = rclcpp::Node::make_shared("go2_rviz_keyboard_teleop_panel");
  pub_ = node_->create_publisher<geometry_msgs::msg::Twist>("/cmd_vel_keyboard", 10);

  publish_timer_ = new QTimer(this);
  connect(publish_timer_, &QTimer::timeout, this, &KeyboardTeleopPanel::onPublishTimer);
  publish_timer_->start(1000 / kPublishRateHz);

  updateStatus();
}

KeyboardTeleopPanel::~KeyboardTeleopPanel()
{
  publishStop();
}

void KeyboardTeleopPanel::updateStatus()
{
  status_label_->setText(QString(
    "Click here, then hold keys to drive.\n"
    "W/S forward-back, A/D turn, Q/E strafe\n"
    "Z/X speed down/up, Space/Esc stop\n"
    "\n"
    "Speed: linear=%1 m/s, angular=%2 rad/s\n"
    "Held: %3")
    .arg(linear_speed_, 0, 'f', 2)
    .arg(angular_speed_, 0, 'f', 2)
    .arg(held_keys_.isEmpty() ? "(none)" : QString::number(held_keys_.size()) + " key(s)"));
}

void KeyboardTeleopPanel::publishStop()
{
  pub_->publish(geometry_msgs::msg::Twist());
}

void KeyboardTeleopPanel::onPublishTimer()
{
  // Publish only while a key is held. An idle stream of zeros on
  // /cmd_vel_keyboard (twist_mux priority 9) would hold the keyboard lane
  // active forever and block Nav2, the agent and object navigation.
  // Releasing the last key sends one stop (keyReleaseEvent).
  if (held_keys_.isEmpty()) {
    return;
  }
  geometry_msgs::msg::Twist msg;
  if (held_keys_.contains(Qt::Key_W)) {
    msg.linear.x += linear_speed_;
  }
  if (held_keys_.contains(Qt::Key_S)) {
    msg.linear.x -= linear_speed_;
  }
  if (held_keys_.contains(Qt::Key_Q)) {
    msg.linear.y += linear_speed_;
  }
  if (held_keys_.contains(Qt::Key_E)) {
    msg.linear.y -= linear_speed_;
  }
  if (held_keys_.contains(Qt::Key_A)) {
    msg.angular.z += angular_speed_;
  }
  if (held_keys_.contains(Qt::Key_D)) {
    msg.angular.z -= angular_speed_;
  }
  pub_->publish(msg);
}

void KeyboardTeleopPanel::keyPressEvent(QKeyEvent * event)
{
  // Auto-repeat presses (held key firing repeatedly while down) would
  // otherwise look identical to a fresh press; ignoring them keeps the
  // held-key set accurate between the real press and the real release.
  if (event->isAutoRepeat()) {
    event->ignore();
    return;
  }

  switch (event->key()) {
    case Qt::Key_W:
    case Qt::Key_S:
    case Qt::Key_A:
    case Qt::Key_D:
    case Qt::Key_Q:
    case Qt::Key_E:
      held_keys_.insert(event->key());
      updateStatus();
      break;
    case Qt::Key_Z:
      linear_speed_ = std::max(kLinearSpeedMin, linear_speed_ - kLinearSpeedStep);
      angular_speed_ = std::max(kAngularSpeedMin, angular_speed_ - kAngularSpeedStep);
      updateStatus();
      break;
    case Qt::Key_X:
      linear_speed_ = std::min(kLinearSpeedMax, linear_speed_ + kLinearSpeedStep);
      angular_speed_ = std::min(kAngularSpeedMax, angular_speed_ + kAngularSpeedStep);
      updateStatus();
      break;
    case Qt::Key_Space:
    case Qt::Key_Escape:
      held_keys_.clear();
      publishStop();
      updateStatus();
      break;
    default:
      QWidget::keyPressEvent(event);
      return;
  }
  event->accept();
}

void KeyboardTeleopPanel::keyReleaseEvent(QKeyEvent * event)
{
  if (event->isAutoRepeat()) {
    event->ignore();
    return;
  }
  if (held_keys_.remove(event->key())) {
    if (held_keys_.isEmpty()) {
      publishStop();
    }
    updateStatus();
    event->accept();
  } else {
    QWidget::keyReleaseEvent(event);
  }
}

void KeyboardTeleopPanel::focusOutEvent(QFocusEvent * event)
{
  // Clicking away while a key is physically still held must stop the robot
  // immediately rather than leave it driving with no way to release the
  // key from this widget anymore.
  held_keys_.clear();
  publishStop();
  updateStatus();
  QWidget::focusOutEvent(event);
}

}  // namespace go2_rviz_plugins

#include <pluginlib/class_list_macros.hpp>
PLUGINLIB_EXPORT_CLASS(go2_rviz_plugins::KeyboardTeleopPanel, rviz_common::Panel)
