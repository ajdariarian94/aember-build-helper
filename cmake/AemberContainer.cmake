# AemberContainer.cmake: pack CMake targets into an aember-ready LXC container.
#
#   list(APPEND CMAKE_MODULE_PATH ${CMAKE_SOURCE_DIR}/tools/aember-build-helper/cmake)
#   include(AemberContainer)
#   install(TARGETS hello RUNTIME DESTINATION usr/bin)
#   aember_container(hello
#     MANIFEST ${CMAKE_SOURCE_DIR}/aember-container.json
#     DEPENDS hello)
#
# Adds the target `<name>-aember-container`: installs the project into a
# staging directory (cmake --install, prefix "/"-relative: give install()
# destinations like usr/bin), then runs `aember-cli/run.py build --rootfs-dir` on
# it, so the manifest's "libs" (e.g. the aember SDK sysroot) adds the shared
# libraries the binaries need. Output: ${CMAKE_BINARY_DIR}/aember-out/<name>/.
#
# Options: OUT_DIR <dir> (default ${CMAKE_BINARY_DIR}/aember-out),
#          ARCH <aember arch> (overrides the manifest's "arch"),
#          ALL (build it with the default target).

set(_AEMBER_BUILD_HELPER_DIR "${CMAKE_CURRENT_LIST_DIR}/.." CACHE INTERNAL "")

function(aember_container name)
  cmake_parse_arguments(AC "ALL" "MANIFEST;OUT_DIR;ARCH" "DEPENDS" ${ARGN})
  if(NOT AC_MANIFEST)
    set(AC_MANIFEST "${CMAKE_CURRENT_SOURCE_DIR}/aember-container.json")
  endif()
  if(NOT AC_OUT_DIR)
    set(AC_OUT_DIR "${CMAKE_BINARY_DIR}/aember-out")
  endif()
  find_package(Python3 3.10 REQUIRED COMPONENTS Interpreter)

  set(staging "${CMAKE_BINARY_DIR}/aember-staging/${name}")
  set(arch_args "")
  if(AC_ARCH)
    set(arch_args --arch ${AC_ARCH})
  endif()
  set(all_flag "")
  if(AC_ALL)
    set(all_flag ALL)
  endif()

  add_custom_target(
    ${name}-aember-container ${all_flag}
    COMMAND ${CMAKE_COMMAND} -E rm -rf "${staging}"
    COMMAND ${CMAKE_COMMAND} --install "${CMAKE_BINARY_DIR}" --prefix "${staging}"
    COMMAND
      ${Python3_EXECUTABLE} "${_AEMBER_BUILD_HELPER_DIR}/aember-cli/run.py" build
      --manifest "${AC_MANIFEST}" --out "${AC_OUT_DIR}" --rootfs-dir "${staging}"
      ${arch_args}
    DEPENDS ${AC_DEPENDS}
    WORKING_DIRECTORY "${CMAKE_BINARY_DIR}"
    COMMENT "aember: container ${name} → ${AC_OUT_DIR}/${name}"
    VERBATIM)
endfunction()
