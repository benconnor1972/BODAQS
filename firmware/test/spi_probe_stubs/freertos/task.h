#pragma once
#include "FreeRTOS.h"
struct FakeTask;
using TaskHandle_t = FakeTask*;
BaseType_t xTaskCreatePinnedToCore(void (*fn)(void*), const char*, uint32_t, void*, int, TaskHandle_t*, int);
TaskHandle_t xTaskGetCurrentTaskHandle();
int xPortGetCoreID();
void vTaskDelay(TickType_t ticks);
void vTaskDelete(TaskHandle_t);
void vTaskNotifyGiveFromISR(TaskHandle_t, BaseType_t*);
uint32_t ulTaskNotifyTake(BaseType_t, TickType_t);
