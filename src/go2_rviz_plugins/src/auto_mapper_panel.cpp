#include "go2_rviz_plugins/auto_mapper_panel.hpp"

#include <csignal>
#include <unistd.h>

#include <QHBoxLayout>
#include <QLabel>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QTimer>
#include <QVBoxLayout>

namespace go2_rviz_plugins
{

namespace
{
// How long to wait after a graceful SIGINT (the Ctrl+C-equivalent path
// explorer.py's own shutdown handling expects, so it cancels any in-flight
// Nav2 goal) before giving up and force-killing the process.
constexpr int kGracefulStopTimeoutMs = 5000;

// Re-enable the Scan button if the explorer never answers the request.
constexpr int kScanReplyTimeoutMs = 5000;

constexpr char kScanService[] = "/frontier_explorer/scan";
}  // namespace

AutoMapperPanel::AutoMapperPanel(QWidget * parent)
: rviz_common::Panel(parent)
{
  start_stop_button_ = new QPushButton("Start", this);
  scan_button_ = new QPushButton("Scan", this);
  scan_button_->setToolTip(
    "Turn the robot 360 degrees so SLAM can re-place it on the map. "
    "Pauses the current goal; needs the explorer running.");
  status_label_ = new QLabel("Stopped", this);
  log_view_ = new QPlainTextEdit(this);
  log_view_->setReadOnly(true);
  log_view_->setMaximumBlockCount(1000);

  auto * buttons = new QHBoxLayout();
  buttons->addWidget(start_stop_button_);
  buttons->addWidget(scan_button_);

  auto * layout = new QVBoxLayout(this);
  layout->addWidget(status_label_);
  layout->addLayout(buttons);
  layout->addWidget(log_view_, /*stretch=*/1);
  setLayout(layout);

  node_ = rclcpp::Node::make_shared("go2_rviz_auto_mapper_panel");
  scan_client_ = node_->create_client<std_srvs::srv::Trigger>(kScanService);
  executor_.add_node(node_);
  spin_thread_ = std::thread([this]() {executor_.spin();});

  connect(scan_button_, &QPushButton::clicked, this, &AutoMapperPanel::onScanClicked);
  connect(this, &AutoMapperPanel::scanReplied, this, &AutoMapperPanel::onScanReplied);

  process_ = new QProcess(this);
  process_->setProcessChannelMode(QProcess::SeparateChannels);

  connect(start_stop_button_, &QPushButton::clicked, this, &AutoMapperPanel::onStartStopClicked);
  connect(process_, &QProcess::readyReadStandardOutput, this, &AutoMapperPanel::onReadyReadStandardOutput);
  connect(process_, &QProcess::readyReadStandardError, this, &AutoMapperPanel::onReadyReadStandardError);
  connect(process_, &QProcess::started, this, &AutoMapperPanel::onProcessStarted);
  connect(
    process_, QOverload<int, QProcess::ExitStatus>::of(&QProcess::finished),
    this, &AutoMapperPanel::onProcessFinished);
  connect(process_, &QProcess::errorOccurred, this, &AutoMapperPanel::onProcessErrorOccurred);
}

AutoMapperPanel::~AutoMapperPanel()
{
  // Stop the spin thread first: a late service reply must not call back into
  // a panel that's being destroyed.
  executor_.cancel();
  if (spin_thread_.joinable()) {
    spin_thread_.join();
  }

  if (process_->state() != QProcess::NotRunning) {
    ::kill(static_cast<pid_t>(process_->processId()), SIGINT);
    process_->waitForFinished(kGracefulStopTimeoutMs);
    if (process_->state() != QProcess::NotRunning) {
      process_->kill();
      process_->waitForFinished(1000);
    }
  }
}

void AutoMapperPanel::setStatus(const QString & text)
{
  status_label_->setText(text);
}

void AutoMapperPanel::appendLog(const QString & text)
{
  for (const QString & line : text.split('\n', Qt::SkipEmptyParts)) {
    log_view_->appendPlainText(line);
  }
}

void AutoMapperPanel::onStartStopClicked()
{
  if (process_->state() == QProcess::NotRunning) {
    stopping_ = false;
    log_view_->clear();
    setStatus("Starting...");
    start_stop_button_->setEnabled(false);
    // Inherits this process's environment, which is already ROS-sourced
    // since rviz2 itself was launched through ros2 launch.
    process_->start("ros2", {"run", "go2_auto_mapper", "explorer"});
  } else {
    stopping_ = true;
    setStatus("Stopping...");
    start_stop_button_->setEnabled(false);
    // SIGINT (not QProcess::terminate()'s SIGTERM) so explorer.py's own
    // KeyboardInterrupt/ExternalShutdownException handling runs and cancels
    // any in-flight Nav2 goal before exiting, matching the stop behavior
    // documented in go2_auto_mapper/README.md.
    ::kill(static_cast<pid_t>(process_->processId()), SIGINT);
    QTimer::singleShot(kGracefulStopTimeoutMs, this, &AutoMapperPanel::onForceKillTimeout);
  }
}

void AutoMapperPanel::onScanClicked()
{
  if (!scan_client_->service_is_ready()) {
    appendLog("[panel] Scan: the explorer isn't running. Press Start first.");
    return;
  }

  scan_button_->setEnabled(false);
  QTimer::singleShot(kScanReplyTimeoutMs, this, [this]() {scan_button_->setEnabled(true);});

  auto request = std::make_shared<std_srvs::srv::Trigger::Request>();
  scan_client_->async_send_request(
    request,
    [this](rclcpp::Client<std_srvs::srv::Trigger>::SharedFuture future) {
      const auto response = future.get();
      emit scanReplied(response->success, QString::fromStdString(response->message));
    });
}

void AutoMapperPanel::onScanReplied(bool success, const QString & message)
{
  scan_button_->setEnabled(true);
  appendLog(QString("[panel] Scan: %1").arg(success ? message : "refused, " + message));
}

void AutoMapperPanel::onForceKillTimeout()
{
  if (stopping_ && process_->state() != QProcess::NotRunning) {
    appendLog("[panel] No clean exit after SIGINT, force-killing.");
    process_->kill();
  }
}

void AutoMapperPanel::onReadyReadStandardOutput()
{
  appendLog(QString::fromUtf8(process_->readAllStandardOutput()));
}

void AutoMapperPanel::onReadyReadStandardError()
{
  appendLog(QString::fromUtf8(process_->readAllStandardError()));
}

void AutoMapperPanel::onProcessStarted()
{
  setStatus(QString("Running (pid %1)").arg(process_->processId()));
  start_stop_button_->setText("Stop");
  start_stop_button_->setEnabled(true);
}

void AutoMapperPanel::onProcessFinished(int exit_code, QProcess::ExitStatus exit_status)
{
  if (exit_status == QProcess::CrashExit) {
    setStatus(QString("Stopped (signal, exit code %1)").arg(exit_code));
  } else {
    setStatus(QString("Stopped (exit code %1)").arg(exit_code));
  }
  start_stop_button_->setText("Start");
  start_stop_button_->setEnabled(true);
  stopping_ = false;
}

void AutoMapperPanel::onProcessErrorOccurred(QProcess::ProcessError error)
{
  if (error == QProcess::FailedToStart) {
    setStatus("Failed to start (is go2_auto_mapper installed?)");
    start_stop_button_->setText("Start");
    start_stop_button_->setEnabled(true);
  }
}

}  // namespace go2_rviz_plugins

#include <pluginlib/class_list_macros.hpp>
PLUGINLIB_EXPORT_CLASS(go2_rviz_plugins::AutoMapperPanel, rviz_common::Panel)
