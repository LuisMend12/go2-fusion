#pragma once

#include <QSet>
#include <QTimer>

#include <rclcpp/rclcpp.hpp>
#include <rviz_common/panel.hpp>

#include <geometry_msgs/msg/twist.hpp>

class QLabel;
class QFocusEvent;
class QKeyEvent;

namespace go2_rviz_plugins
{

// Drives /cmd_vel_keyboard (twist_mux keyboard input, same as keyboard_teleop)
// from real Qt key press/release events while this panel has
// focus. Unlike keyboard_teleop.py (which reads a raw terminal and has no
// way to detect a key-up, only a key-repeat timeout), Qt delivers genuine
// release events, so held keys are tracked directly instead of needing an
// AXIS_HOLD_TIMEOUT watchdog — losing focus (click elsewhere) or Space/Esc
// clears all of them and publishes an immediate zero Twist.
class KeyboardTeleopPanel : public rviz_common::Panel
{
  Q_OBJECT

public:
  explicit KeyboardTeleopPanel(QWidget * parent = nullptr);
  ~KeyboardTeleopPanel() override;

protected:
  void keyPressEvent(QKeyEvent * event) override;
  void keyReleaseEvent(QKeyEvent * event) override;
  void focusOutEvent(QFocusEvent * event) override;

private slots:
  void onPublishTimer();

private:
  void publishStop();
  void updateStatus();

  rclcpp::Node::SharedPtr node_;
  rclcpp::Publisher<geometry_msgs::msg::Twist>::SharedPtr pub_;
  QTimer * publish_timer_;

  QSet<int> held_keys_;
  double linear_speed_;
  double angular_speed_;

  QLabel * status_label_;
};

}  // namespace go2_rviz_plugins
