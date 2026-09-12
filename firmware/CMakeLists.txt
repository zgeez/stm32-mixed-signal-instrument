cmake_minimum_required(VERSION 3.22)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Debug)
endif()

project(firmware LANGUAGES C ASM)
add_executable(firmware)
add_subdirectory(cmake/stm32cubemx)
target_link_libraries(firmware stm32cubemx)
target_sources(firmware PRIVATE
    App/awg/awg.c App/awg/awg_waveform.c App/awg/awg_refill.c
    App/control/protocol.c App/control/commands.c App/control/usb_control.c
    App/scope/scope.c App/scope/scope_trigger.c)
target_include_directories(firmware PRIVATE App/awg App/control App/scope)
