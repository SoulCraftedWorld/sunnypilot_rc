# Install script for directory: /data/openpilot/third_party/libyuv/libyuv

# Set the install prefix
if(NOT DEFINED CMAKE_INSTALL_PREFIX)
  set(CMAKE_INSTALL_PREFIX "/usr/local")
endif()
string(REGEX REPLACE "/$" "" CMAKE_INSTALL_PREFIX "${CMAKE_INSTALL_PREFIX}")

# Set the install configuration name.
if(NOT DEFINED CMAKE_INSTALL_CONFIG_NAME)
  if(BUILD_TYPE)
    string(REGEX REPLACE "^[^A-Za-z0-9_]+" ""
           CMAKE_INSTALL_CONFIG_NAME "${BUILD_TYPE}")
  else()
    set(CMAKE_INSTALL_CONFIG_NAME "")
  endif()
  message(STATUS "Install configuration: \"${CMAKE_INSTALL_CONFIG_NAME}\"")
endif()

# Set the component getting installed.
if(NOT CMAKE_INSTALL_COMPONENT)
  if(COMPONENT)
    message(STATUS "Install component: \"${COMPONENT}\"")
    set(CMAKE_INSTALL_COMPONENT "${COMPONENT}")
  else()
    set(CMAKE_INSTALL_COMPONENT)
  endif()
endif()

# Install shared libraries without execute permission?
if(NOT DEFINED CMAKE_INSTALL_SO_NO_EXE)
  set(CMAKE_INSTALL_SO_NO_EXE "1")
endif()

# Is this installation the result of a crosscompile?
if(NOT DEFINED CMAKE_CROSSCOMPILING)
  set(CMAKE_CROSSCOMPILING "FALSE")
endif()

# Set default install directory permissions.
if(NOT DEFINED CMAKE_OBJDUMP)
  set(CMAKE_OBJDUMP "/usr/bin/objdump")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib" TYPE STATIC_LIBRARY FILES "/data/openpilot/third_party/libyuv/libyuv/libyuv.a")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  include("/data/openpilot/third_party/libyuv/libyuv/CMakeFiles/yuv.dir/install-cxx-module-bmi-noconfig.cmake" OPTIONAL)
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/include/libyuv" TYPE FILE FILES
    "/data/openpilot/third_party/libyuv/libyuv/include/libyuv/basic_types.h"
    "/data/openpilot/third_party/libyuv/libyuv/include/libyuv/compare.h"
    "/data/openpilot/third_party/libyuv/libyuv/include/libyuv/convert.h"
    "/data/openpilot/third_party/libyuv/libyuv/include/libyuv/convert_argb.h"
    "/data/openpilot/third_party/libyuv/libyuv/include/libyuv/convert_from.h"
    "/data/openpilot/third_party/libyuv/libyuv/include/libyuv/convert_from_argb.h"
    "/data/openpilot/third_party/libyuv/libyuv/include/libyuv/cpu_id.h"
    "/data/openpilot/third_party/libyuv/libyuv/include/libyuv/macros_msa.h"
    "/data/openpilot/third_party/libyuv/libyuv/include/libyuv/planar_functions.h"
    "/data/openpilot/third_party/libyuv/libyuv/include/libyuv/rotate.h"
    "/data/openpilot/third_party/libyuv/libyuv/include/libyuv/rotate_argb.h"
    "/data/openpilot/third_party/libyuv/libyuv/include/libyuv/rotate_row.h"
    "/data/openpilot/third_party/libyuv/libyuv/include/libyuv/row.h"
    "/data/openpilot/third_party/libyuv/libyuv/include/libyuv/scale.h"
    "/data/openpilot/third_party/libyuv/libyuv/include/libyuv/scale_argb.h"
    "/data/openpilot/third_party/libyuv/libyuv/include/libyuv/scale_row.h"
    "/data/openpilot/third_party/libyuv/libyuv/include/libyuv/version.h"
    "/data/openpilot/third_party/libyuv/libyuv/include/libyuv/video_common.h"
    "/data/openpilot/third_party/libyuv/libyuv/include/libyuv/mjpeg_decoder.h"
    )
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/include" TYPE FILE FILES "/data/openpilot/third_party/libyuv/libyuv/include/libyuv.h")
endif()

if(CMAKE_INSTALL_COMPONENT)
  set(CMAKE_INSTALL_MANIFEST "install_manifest_${CMAKE_INSTALL_COMPONENT}.txt")
else()
  set(CMAKE_INSTALL_MANIFEST "install_manifest.txt")
endif()

string(REPLACE ";" "\n" CMAKE_INSTALL_MANIFEST_CONTENT
       "${CMAKE_INSTALL_MANIFEST_FILES}")
file(WRITE "/data/openpilot/third_party/libyuv/libyuv/${CMAKE_INSTALL_MANIFEST}"
     "${CMAKE_INSTALL_MANIFEST_CONTENT}")
