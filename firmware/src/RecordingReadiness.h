#pragma once
#include "RecordingAdmissionDecision.h"
#include <stddef.h>
#if defined(BODAQS_UNQUALIFIED_INTEGRATION_CANDIDATE) && BODAQS_UNQUALIFIED_INTEGRATION_CANDIDATE != 0 && BODAQS_UNQUALIFIED_INTEGRATION_CANDIDATE != 1
#error "Candidate override must be 0 or 1"
#endif
#if BODAQS_UNQUALIFIED_INTEGRATION_CANDIDATE && !BODAQS_PRODUCTION_RECORDING
#error "Candidate override belongs only to the explicit integration environment"
#endif

struct LoggerConfig;
namespace RecordingReadiness {
// A trusted qualification module supplies coverage for the complete selected
// load. No numerical policy or historical bench allow-list is installed here.
// Registration belongs to the control owner while idle; callback and strings must have static lifetime.
// Coverage is bounded/pure: no acquisition, control transactions or resource reservation.
struct QualificationProfile {
  const char* identifier=nullptr;
  uint32_t revision=0;
  const char* boardProfile=nullptr;
  const char* acquisitionContract=nullptr;
  RecordingAdmission::Qualification (*coverage)(const LoggerConfig&,uint32_t selectedMask)=nullptr;
};
constexpr const char* kAcquisitionContract="a8-count-first-bulk512-v1";
struct Observation {
  RecordingAdmission::Decision decision;
  uint32_t invalid=0,unavailable=0;
  RecordingAdmission::Reservation reservation=RecordingAdmission::Reservation::NotAttempted;
  char profileId[40]{};
  uint32_t profileRevision=0;
};
bool setQualificationProfile(const QualificationProfile*);
bool candidateBuild();
// Idle status performs no acquisition reservation, sensor read, FIFO consumption or PREPARE.
Observation observe(const LoggerConfig&);
// Control-owner preparation and finalization barriers. Storage may inspect the
// frozen session while writing its header/footer; updates happen outside I/O.
bool beginPreparation(const LoggerConfig&);
bool freezeMembership(const LoggerConfig&,uint32_t availableMask);
void setReservation(RecordingAdmission::Reservation);
const Observation& session();
bool selected(uint8_t configuredIndex);
const char* reason(const Observation&);
}
