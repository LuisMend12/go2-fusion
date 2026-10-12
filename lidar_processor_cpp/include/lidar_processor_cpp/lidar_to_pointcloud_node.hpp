// Copyright (c) 2024, RoboVerse community
// SPDX-License-Identifier: BSD-3-Clause

#ifndef LIDAR_PROCESSOR_CPP__LIDAR_TO_POINTCLOUD_NODE_HPP_
#define LIDAR_PROCESSOR_CPP__LIDAR_TO_POINTCLOUD_NODE_HPP_

#include <deque>
#include <memory>
#include <vector>
#include <string>
#include <unordered_set>
#include <mutex>
#include <atomic>
#include <thread>

#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/point_cloud2.hpp"
#include "std_msgs/msg/header.hpp"
#include "pcl/point_cloud.h"
#include "pcl/point_types.h"
#include "pcl/io/ply_io.h"
#include "pcl/filters/voxel_grid.h"
#include "pcl_conversions/pcl_conversions.h"

namespace lidar_processor_cpp
{

struct LidarConfig
{
  std::vector<std::string> robot_ip_list;
  std::string map_name;
  bool save_map;
  double save_interval;  // seconds
  int max_points;        // Maximum points to keep in memory
  double voxel_size;     // Voxel downsampling size
  double publish_rate;   // Hz, independent of incoming scan rate
};

struct Point3D
{
  float x, y, z;
  
  Point3D(float x_val, float y_val, float z_val) 
    : x(x_val), y(y_val), z(z_val) {}
  
  bool operator==(const Point3D& other) const 
  {
    return std::abs(x - other.x) < 1e-6 && 
           std::abs(y - other.y) < 1e-6 && 
           std::abs(z - other.z) < 1e-6;
  }
};

struct Point3DHash
{
  std::size_t operator()(const Point3D& p) const
  {
    // Round to 3 decimal places for hashing
    int x_int = static_cast<int>(std::round(p.x * 1000));
    int y_int = static_cast<int>(std::round(p.y * 1000));
    int z_int = static_cast<int>(std::round(p.z * 1000));

    // boost::hash_combine-style mixing instead of packing all three ints
    // into one 64-bit value: the previous packing shifted y_int left by
    // only 16 bits (not 32), so its own upper bits overlapped x_int's
    // range, and z_int (unshifted) overlapped the lower half of
    // y_int << 16 - causing materially more hash collisions than a correct
    // disjoint packing as the point count grows into the hundreds of
    // thousands.
    std::size_t seed = 0;
    auto combine = [&seed](int v) {
      seed ^= std::hash<int>{}(v) + 0x9e3779b9 + (seed << 6) + (seed >> 2);
    };
    combine(x_int);
    combine(y_int);
    combine(z_int);
    return seed;
  }
};

class PointCloudAggregator
{
public:
  explicit PointCloudAggregator(const LidarConfig& config);
  
  void addPoints(const std::vector<Point3D>& new_points);
  std::vector<Point3D> getPointsCopy() const;
  bool hasChanges() const;
  void markSaved();
  int getPointCount() const;

private:
  LidarConfig config_;
  std::unordered_set<Point3D, Point3DHash> points_;
  // Tracks true insertion order so eviction can drop the actually-oldest
  // points in O(1) each, instead of sorting the whole set by distance from
  // the origin under the lock every time the cap is hit (which also
  // permanently capped the usable mapped area to whatever was closest to
  // (0,0,0), not whatever was oldest).
  std::deque<Point3D> insertion_order_;
  mutable std::mutex points_mutex_;
  std::atomic<bool> points_changed_;
};

class LidarToPointCloudNode : public rclcpp::Node
{
public:
  LidarToPointCloudNode();

private:
  void declareParameters();
  LidarConfig loadConfiguration();
  void setupSubscriptions();
  void setupPublishers();
  void lidarCallback(const sensor_msgs::msg::PointCloud2::SharedPtr msg);
  void publishTimerCallback();
  void publishAggregatedPointcloud(const std_msgs::msg::Header& header);
  void saveMapCallback();
  void logConfiguration();

  LidarConfig config_;
  std::unique_ptr<PointCloudAggregator> aggregator_;

  std::vector<rclcpp::Subscription<sensor_msgs::msg::PointCloud2>::SharedPtr> subscriptions_;
  rclcpp::Publisher<sensor_msgs::msg::PointCloud2>::SharedPtr pointcloud_pub_;
  rclcpp::TimerBase::SharedPtr save_timer_;
  rclcpp::TimerBase::SharedPtr publish_timer_;
  std::unique_ptr<std_msgs::msg::Header> last_header_;
};

}  // namespace lidar_processor_cpp

#endif  // LIDAR_PROCESSOR_CPP__LIDAR_TO_POINTCLOUD_NODE_HPP_