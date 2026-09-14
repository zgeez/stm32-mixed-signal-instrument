cmake_minimum_required(VERSION 3.22)
project(firmware_tests LANGUAGES C)
enable_testing()

# Off by default: MSVC and the MinGW toolchain used on Windows ship no runtime for these,
# so a default of ON would break the build most people run first. CI turns it on for a
# second pass over the same suites, which checks the firmware sources for memory errors and
# undefined behaviour as well as for the answers they return.
option(FIRMWARE_TESTS_SANITIZE "Build the suites with ASan and UBSan" OFF)
# Also off by default, and never on at the same time as the sanitizers: both instrument the
# generated code, and a build carrying either is not the build anyone should be timing.
option(FIRMWARE_TESTS_COVERAGE "Build the suites with gcov instrumentation" OFF)

add_executable(test_awg test_awg.c ../App/awg/awg_waveform.c)
target_include_directories(test_awg PRIVATE ../App/awg)
add_executable(test_awg_refill test_awg_refill.c ../App/awg/awg_refill.c)
target_include_directories(test_awg_refill PRIVATE ../App/awg)
add_executable(test_protocol test_protocol.c ../App/control/protocol.c ../App/control/commands.c
    ../App/control/ownership.c ../App/probe/probe_divider.c)
target_include_directories(test_protocol PRIVATE ../App/control ../App/awg ../App/scope
    ../App/logic ../App/rtos ../App/probe ../App/mixed)
add_executable(test_scope_trigger test_scope_trigger.c ../App/scope/scope_trigger.c)
target_include_directories(test_scope_trigger PRIVATE ../App/scope)
add_executable(test_probe_divider test_probe_divider.c ../App/probe/probe_divider.c)
target_include_directories(test_probe_divider PRIVATE ../App/probe)
add_executable(test_mixed_policy test_mixed_policy.c ../App/mixed/mixed_policy.c)
target_include_directories(test_mixed_policy PRIVATE ../App/mixed ../App/scope ../App/logic)
add_executable(test_ownership test_ownership.c ../App/control/ownership.c)
target_include_directories(test_ownership PRIVATE ../App/control)
add_executable(test_logic_trigger test_logic_trigger.c ../App/logic/logic_trigger.c)
target_include_directories(test_logic_trigger PRIVATE ../App/logic)
add_executable(test_usb_control test_usb_control.c ../App/control/usb_control.c ../App/control/protocol.c)
target_include_directories(test_usb_control PRIVATE stubs ../App/control)

foreach(target test_awg test_awg_refill test_protocol test_usb_control test_scope_trigger
        test_logic_trigger test_ownership test_probe_divider test_mixed_policy)
    target_compile_features(${target} PRIVATE c_std_11)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /WX)
        target_compile_definitions(${target} PRIVATE _CRT_SECURE_NO_WARNINGS)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -Werror)
    endif()
    if(FIRMWARE_TESTS_COVERAGE)
        target_compile_options(${target} PRIVATE --coverage -O0 -g)
        target_link_options(${target} PRIVATE --coverage)
    endif()
    if(FIRMWARE_TESTS_SANITIZE)
        # Recovering from a finding would print it and carry on to a passing exit code, so
        # the suite would go green with the bug still in it. These make the first finding
        # fatal, which is the difference between a check and a log message.
        target_compile_options(${target} PRIVATE -fsanitize=address,undefined
            -fno-sanitize-recover=all -fno-omit-frame-pointer -g)
        target_link_options(${target} PRIVATE -fsanitize=address,undefined)
    endif()
endforeach()
if(NOT MSVC)
    target_link_libraries(test_awg PRIVATE m)
endif()

add_test(NAME awg_algorithms COMMAND test_awg)
add_test(NAME awg_refill COMMAND test_awg_refill)
add_test(NAME protocol COMMAND test_protocol ${CMAKE_CURRENT_SOURCE_DIR}/../../protocol/vectors.txt)
add_test(NAME usb_control COMMAND test_usb_control)
add_test(NAME scope_trigger COMMAND test_scope_trigger)
add_test(NAME logic_trigger COMMAND test_logic_trigger)
add_test(NAME ownership COMMAND test_ownership)
add_test(NAME probe_divider COMMAND test_probe_divider)
add_test(NAME mixed_policy COMMAND test_mixed_policy)
