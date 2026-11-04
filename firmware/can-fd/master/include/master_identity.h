#ifndef MASTER_IDENTITY_H
#define MASTER_IDENTITY_H

#include "bodaqs_master_protocol.h"

#define BODAQS_MASTER_FIRMWARE_VERSION (0x00010008U)

BodaqsMasterIdentity master_identity_read(void);

#endif

