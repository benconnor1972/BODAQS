#pragma once
#include "FreeRTOS.h"
using SemaphoreHandle_t = std::timed_mutex*;
SemaphoreHandle_t xSemaphoreCreateMutex();
BaseType_t xSemaphoreTake(SemaphoreHandle_t, TickType_t);
void xSemaphoreGive(SemaphoreHandle_t);
