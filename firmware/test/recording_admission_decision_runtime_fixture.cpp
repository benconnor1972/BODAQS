#include "RecordingAdmissionDecision.h"
#include <cassert>
using namespace RecordingAdmission;

int main() {
  Inputs input;input.requested=15;input.available=7;
  input.qualification=Qualification::Covered;input.profilePresent=true;
  auto result=decide(input);
  assert(!result.mayPrepare && result.blocker==Blocker::ParticipantUnavailable && result.excluded==8);
  input.bestEffort=true;result=decide(input);
  assert(result.mayPrepare && !result.mayRecord && result.selected==7 && result.excluded==8);
  input.reservation=Reservation::Acquired;result=decide(input);
  assert(result.mayPrepare && result.mayRecord && result.qualified && !result.candidate);
  input.invalid=8;result=decide(input);
  assert(!result.mayPrepare && result.blocker==Blocker::InvalidConfiguration);
  input.invalid=0;input.available=0;result=decide(input);
  assert(!result.mayPrepare && result.blocker==Blocker::NoParticipants);
  input.available=15;input.qualification=Qualification::Unknown;result=decide(input);
  assert(!result.mayPrepare && !result.qualified && result.blocker==Blocker::Unqualified);
  input.candidateBuild=true;result=decide(input);
  assert(result.mayRecord && result.candidate && !result.qualified);
  input.qualification=Qualification::Rejected;result=decide(input);
  assert(!result.mayPrepare && !result.candidate); // An override cannot bypass known rejection.
  input.qualification=Qualification::Covered;input.profilePresent=false;result=decide(input);
  assert(!result.mayPrepare && result.blocker==Blocker::InvalidQualification);
  input.profilePresent=true;input.reservation=Reservation::Failed;result=decide(input);
  assert(!result.mayPrepare && result.blocker==Blocker::ReservationFailed);
  input.reservation=Reservation::Acquired;input.owned=true;result=decide(input);
  assert(!result.mayPrepare && result.blocker==Blocker::OwnershipRetained);
  input.owned=false;input.qualification=static_cast<Qualification>(255);result=decide(input);
  assert(!result.mayPrepare && result.blocker==Blocker::InvalidQualification);
  input.qualification=Qualification::Covered;input.migrationPending=true;result=decide(input);
  assert(!result.mayPrepare && result.blocker==Blocker::MigrationRequired);
}
