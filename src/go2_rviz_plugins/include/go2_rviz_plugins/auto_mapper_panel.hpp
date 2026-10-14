#pragma once

#include <QProcess>

#include <rviz_common/panel.hpp>

class QLabel;
class QPlainTextEdit;
class QPushButton;

namespace go2_rviz_plugins
{

// Runs `ros2 run go2_auto_mapper explorer` as a child process and surfaces
// start/stop controls plus its log output. This only manages the process;
// it does not talk to the explorer node over ROS, so there's no frontier
// count or live goal display here (see go2_auto_mapper/README.md for what
// the node itself does and how to stop it safely by hand if this panel
// isn't used).
class AutoMapperPanel : public rviz_common::Panel
{
  Q_OBJECT

public:
  explicit AutoMapperPanel(QWidget * parent = nullptr);
  ~AutoMapperPanel() override;

private slots:
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
  QLabel * status_label_;
  QPlainTextEdit * log_view_;
  bool stopping_{false};
};

}  // namespace go2_rviz_plugins
