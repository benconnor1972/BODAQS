#pragma once
#include <mutex>
#include <stdint.h>
using BaseType_t = int;
using TickType_t = uint32_t;
using portMUX_TYPE = std::recursive_mutex;
#define portMUX_INITIALIZER_UNLOCKED {}
#define portENTER_CRITICAL(p) (p)->lock()
#define portEXIT_CRITICAL(p) (p)->unlock()
void probeEnterCriticalIsr(portMUX_TYPE* mux);
#define portENTER_CRITICAL_ISR(p) probeEnterCriticalIsr(p)
#define portEXIT_CRITICAL_ISR(p) (p)->unlock()
#define portYIELD_FROM_ISR() ((void)0)
#define pdTRUE 1
#define pdFALSE 0
#define pdPASS 1
#define configTICK_RATE_HZ 1000
#define pdMS_TO_TICKS(n) (n)
