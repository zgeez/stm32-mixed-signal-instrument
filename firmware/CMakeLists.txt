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
    App/scope/scope.c App/scope/scope_trigger.c
    App/logic/logic.c App/logic/logic_trigger.c
    App/control/ownership.c App/rtos/tasks.c
    App/probe/probe.c App/probe/probe_divider.c
    App/mixed/mixed.c App/mixed/mixed_policy.c)
target_include_directories(firmware PRIVATE
    App/awg App/control App/scope App/logic App/rtos App/probe App/mixed)

# The device reports a build identity so a result or a bug report can be tied to the image
# that produced it. Read at configure time: rebuilding after new commits without re-running
# CMake keeps the older id, and the application reports whatever the board actually says.
execute_process(
    COMMAND git rev-parse --short HEAD
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
    OUTPUT_VARIABLE FIRMWARE_BUILD_ID
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET)
if(NOT FIRMWARE_BUILD_ID)
    set(FIRMWARE_BUILD_ID "unknown")
endif()
target_compile_definitions(firmware PRIVATE FIRMWARE_BUILD_ID="${FIRMWARE_BUILD_ID}")

# FreeRTOS is vendored from STM32Cube FW_F4 V1.28.3 because the CubeMX X-CUBE-FREERTOS
# pack is not installed, so it is listed here rather than in the generated CMake.
set(FREERTOS_DIR Middlewares/Third_Party/FreeRTOS/Source)
target_sources(firmware PRIVATE
    ${FREERTOS_DIR}/croutine.c ${FREERTOS_DIR}/event_groups.c ${FREERTOS_DIR}/list.c
    ${FREERTOS_DIR}/queue.c ${FREERTOS_DIR}/stream_buffer.c ${FREERTOS_DIR}/tasks.c
    ${FREERTOS_DIR}/timers.c
    ${FREERTOS_DIR}/portable/GCC/ARM_CM4F/port.c
    ${FREERTOS_DIR}/portable/MemMang/heap_4.c
    ${FREERTOS_DIR}/CMSIS_RTOS_V2/cmsis_os2.c)
target_include_directories(firmware PRIVATE
    ${FREERTOS_DIR}/include
    ${FREERTOS_DIR}/portable/GCC/ARM_CM4F
    ${FREERTOS_DIR}/CMSIS_RTOS_V2)
