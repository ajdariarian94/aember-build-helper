# A C++ program packed into an aember container with aember_container().
# Build it with the aember SDK so it matches the target (in the aember dev
# container: source build/aember-resources/<arch>/sdk/environment-setup-*).
cmake_minimum_required(VERSION 3.22)
project(hello-cmake CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# The helper as a submodule would be tools/aember-build-helper; here it is
# this repository.
set(AEMBER_BUILD_HELPER "${CMAKE_CURRENT_SOURCE_DIR}/../.."
    CACHE PATH "aember-build-helper checkout")
list(APPEND CMAKE_MODULE_PATH "${AEMBER_BUILD_HELPER}/cmake")
include(AemberContainer)

add_executable(hello-cmake src/main.cpp)
install(TARGETS hello-cmake RUNTIME DESTINATION usr/bin)

aember_container(hello-cmake
  MANIFEST "${CMAKE_CURRENT_SOURCE_DIR}/aember-container.json"
  DEPENDS hello-cmake)
