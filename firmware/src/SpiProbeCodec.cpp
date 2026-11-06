// PIO keeps the normal full source set. This single guarded wrapper links the
// boundary-reviewed common implementation only into the dedicated bench image.
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
#include "../can-fd/common/protocol/bodaqs_spi_probe.c"
#endif
