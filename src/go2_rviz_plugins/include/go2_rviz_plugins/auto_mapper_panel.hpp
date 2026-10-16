#pragma once

#include <thread>

#include <QProcess>
#include <QString>

#include <rclcpp/rclcpp.hpp>
#include <rviz_common/panel.hpp>
#include <std_srvs/srv/trigger.hpp>

class QLabel;
class QPlainTextEdit;
class QPushButton;

namespace go2_rviz_plugins
{

// Runs `ros2 run go2_auto_mapper explorer` as a child process and surfaces
// start/stop controls plus its log output. The Scan button calls the
// explorer's /frontier_explorer/scan service (a 360 degree turn so SLAM can
// re-place the robot) through a small rclcpp node of the panel's own, spun
// on a background thread like MapViewerPanel's. See
// go2_auto_mapper/README.md for what the node itself does and how to stop it
// safely by hand if this panel isn't used.
class AutoMapperPanel : public rviz_common::Panel
{
  Q_OBJECT

public:
  explicit AutoMapperPanel(QWidget * parent = nullptr);
  ~AutoMapperPanel() override;

signals:
  // Emitted from the ROS spin thread; Qt queues it onto the GUI thread.
  void scanReplied(bool success, const QString & message);

private slots:
  void onScanClicked();
  void onScanReplied(bool success, const QString & message);
  void onStartStopClicked();
  void onReadyReadStandardOutput();
  void onReadyReadStandardError();
  void onProcessStarted();
  void onProcessFinished(int exit_code, QProcess::ExitStatus exit_status);
  void onProcessErrorOccurred(QProcess::ProcessError error);
  void onForceKillTimeout();

private:
  void setStatus(const QString & text);
  void appendLog(const QString & text);

  QProcess * process_;
  QPushButton * start_stop_button_;
  QPushButton * scan_button_;
  QLabel * status_label_;
  QPlainTextEdit * log_view_;
  bool stopping_{false};

  rclcpp::Node::SharedPtr node_;
  rclcpp::executors::SingleThreadedExecutor executor_;
  std::thread spin_thread_;
  rclcpp::Client<std_srvs::srv::Trigger>::SharedPtr scan_client_;
};

}  // namespace go2_rviz_plugins
