#pragma once
#include <stdint.h>

namespace RecordingAdmission {
enum class Qualification : uint8_t { Unknown, Covered, Rejected, Invalid };
enum class Reservation : uint8_t { NotAttempted, Acquired, Failed };
enum class Blocker : uint8_t {
  None,OwnershipRetained,MigrationRequired,InvalidConfiguration,
  ParticipantUnavailable,NoParticipants,InvalidQualification,Unqualified,
  QualificationRejected,ReservationFailed
};

// Bits denote configured sensor indices, never CAN addresses. Configuration and
// availability are observations; qualification comes from a separately supplied
// coverage/budget profile, not from a successful reconciliation or bench case.
struct Inputs {
  uint32_t requested=0,available=0,invalid=0;
  bool bestEffort=false,owned=false,migrationPending=false;
  bool candidateBuild=false,profilePresent=false;
  Qualification qualification=Qualification::Unknown;
  Reservation reservation=Reservation::NotAttempted;
};
struct Decision {
  uint32_t requested=0,selected=0,excluded=0;
  bool mayPrepare=false,mayRecord=false,qualified=false,candidate=false;
  Blocker blocker=Blocker::None;
};
inline Decision decide(const Inputs& input) {
  Decision result;result.requested=input.requested;
  result.selected=input.requested&input.available&~input.invalid;
  result.excluded=input.requested&~result.selected;
  if(input.owned) result.blocker=Blocker::OwnershipRetained;
  else if(input.migrationPending) result.blocker=Blocker::MigrationRequired;
  else if(input.invalid&input.requested) result.blocker=Blocker::InvalidConfiguration;
  else if(!input.bestEffort && result.excluded) result.blocker=Blocker::ParticipantUnavailable;
  else if(!result.selected) result.blocker=Blocker::NoParticipants;
  else if(input.qualification!=Qualification::Unknown && input.qualification!=Qualification::Covered && input.qualification!=Qualification::Rejected)
    result.blocker=Blocker::InvalidQualification;
  else if(input.qualification==Qualification::Covered && !input.profilePresent)
    result.blocker=Blocker::InvalidQualification;
  else if(input.qualification==Qualification::Rejected) result.blocker=Blocker::QualificationRejected;
  else if(input.qualification==Qualification::Unknown && !input.candidateBuild)
    result.blocker=Blocker::Unqualified;
  else if(input.reservation!=Reservation::NotAttempted && input.reservation!=Reservation::Acquired) result.blocker=Blocker::ReservationFailed;
  else {
    result.qualified=input.qualification==Qualification::Covered;
    result.candidate=!result.qualified && input.candidateBuild;
    result.mayPrepare=true;result.mayRecord=input.reservation==Reservation::Acquired;
  }
  return result;
}
inline const char* blockerText(Blocker blocker) {
  switch(blocker) {
    case Blocker::None:return "none";
    case Blocker::OwnershipRetained:return "recording ownership retained";
    case Blocker::MigrationRequired:return "configuration migration requires acknowledgement";
    case Blocker::InvalidConfiguration:return "unsupported or ambiguous sensor configuration";
    case Blocker::ParticipantUnavailable:return "requested participant is unavailable";
    case Blocker::NoParticipants:return "no eligible requested participants";
    case Blocker::InvalidQualification:return "qualification profile is missing or invalid";
    case Blocker::Unqualified:return "no qualification profile covers this configuration";
    case Blocker::QualificationRejected:return "configuration exceeds the supplied qualification profile";
    case Blocker::ReservationFailed:return "recording resource reservation failed";
  }
  return "unknown admission blocker";
}
} // namespace RecordingAdmission
