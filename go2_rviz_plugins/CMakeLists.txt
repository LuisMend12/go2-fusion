cmake_minimum_required(VERSION 3.8)
project(go2_rviz_plugins)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_action REQUIRED)
find_package(rviz_common REQUIRED)
find_package(pluginlib REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav2_msgs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(Qt5 REQUIRED COMPONENTS Widgets)

set(dependencies
  rclcpp
  rclcpp_action
  rviz_common
  pluginlib
  nav_msgs
  geometry_msgs
  nav2_msgs
  tf2
  tf2_ros
)

# CMake's AUTOMOC dependency scanner silently found nothing for these
# headers in this environment (moc itself works fine when invoked by hand —
# verified manually), so panels' Q_OBJECT classes are moc'd explicitly here
# instead of relying on it. qt5_wrap_cpp uses directory-scope include dirs,
# not target properties, hence the explicit include_directories() here.
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/include)
qt5_wrap_cpp(MOC_SOURCES
  include/go2_rviz_plugins/map_viewer_panel.hpp
  include/go2_rviz_plugins/auto_mapper_panel.hpp
  include/go2_rviz_plugins/keyboard_teleop_panel.hpp
)

add_library(${PROJECT_NAME} SHARED
  src/map_viewer_panel.cpp
  src/auto_mapper_panel.cpp
  src/keyboard_teleop_panel.cpp
  ${MOC_SOURCES}
)

target_include_directories(${PROJECT_NAME} PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)

ament_target_dependencies(${PROJECT_NAME} ${dependencies})
target_link_libraries(${PROJECT_NAME} Qt5::Widgets)

# RViz loads panels through pluginlib's class_loader, which dlopen()s this
# library directly rather than linking against it, so symbols must be
# exported by default (matches rviz_common's own plugin examples).
target_compile_definitions(${PROJECT_NAME} PRIVATE "GO2_RVIZ_PLUGINS_BUILDING_LIBRARY")

pluginlib_export_plugin_description_file(rviz_common plugins_description.xml)

install(
  TARGETS ${PROJECT_NAME}
  EXPORT export_${PROJECT_NAME}
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION bin
)
install(DIRECTORY include/ DESTINATION include)

ament_export_include_directories(include)
ament_export_libraries(${PROJECT_NAME})
ament_export_targets(export_${PROJECT_NAME})
ament_export_dependencies(${dependencies})

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  set(ament_cmake_copyright_FOUND TRUE)
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
