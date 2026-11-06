
#include <mutex>
#define ARDUINO_ISR_ATTR
#define LOW 0
#define HIGH 1
#define OUTPUT 1
#define INPUT 0
#define INPUT_PULLUP 2
#define FALLING 2
#define RISING 3
unsigned long micros();
void delayMicroseconds(unsigned int us);
void pinMode(uint8_t pin, uint8_t mode);
void digitalWrite(uint8_t pin, uint8_t level);
int digitalRead(uint8_t pin);
int analogRead(uint8_t pin);
void attachInterruptArg(uint8_t pin, void (*fn)(void*), void* arg, int mode);
void detachInterrupt(uint8_t pin);
