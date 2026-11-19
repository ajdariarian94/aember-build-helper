// Prints a line every 5 s until SIGTERM (aember's graceful container stop).
#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <print>
#include <thread>

namespace {
std::atomic<bool> stop{false};
}

int main() {
  std::signal(SIGTERM, [](int) { stop = true; });
  std::signal(SIGINT, [](int) { stop = true; });
  const char* who = std::getenv("GREETING");
  std::println("hello-cmake: up (C++23, libstdc++ from the aember SDK)");
  for (int n = 1; !stop; ++n) {
    std::println("hello-cmake: hello #{} from {}", n, who ? who : "aember");
    std::fflush(stdout);
    for (int i = 0; i < 50 && !stop; ++i)
      std::this_thread::sleep_for(std::chrono::milliseconds(100));
  }
  std::println("hello-cmake: stopping");
  return 0;
}
