#ifndef BODAQS_CONTROL_AUTHORITY_H
#define BODAQS_CONTROL_AUTHORITY_H
#include "bodaqs_control.h"
#ifdef __cplusplus
extern "C" {
#endif
typedef uint64_t (*BodaqsControlRandom64)(void *context);
typedef struct {
    uint64_t challenge, proposed_session, next_challenge;
    uint32_t challenge_read, challenge_started, high_water;
    BodaqsControlRecord challenge_request, bind_request, bind_result;
    BodaqsControlRecord latest_request, latest_result, release_request, release_result;
    bool challenge_valid, bound_retry, latest_valid, release_valid;
} BodaqsControlAuthority;
void bodaqs_control_authority_init(BodaqsControlAuthority *state);
/* Only authority state and view.session/flag0 change. Caller owns guard flags,
 * configuration provenance and hardware. Time and entropy are boundary inputs. */
bool bodaqs_control_authority_process(BodaqsControlAuthority *state,
    BodaqsControlNode *view, const BodaqsControlRecord *request, uint32_t now,
    BodaqsControlRandom64 random, void *context, BodaqsControlRecord *reply);
/* Future mutation services admit only after validation; a rejected admission
 * does not advance sequence state. Session is checked before cached evidence. */
uint8_t bodaqs_control_authority_admit(BodaqsControlAuthority *state,
    const BodaqsControlNode *view, const BodaqsControlRecord *request);
void bodaqs_control_authority_complete(BodaqsControlAuthority *state,
    const BodaqsControlRecord *request, const BodaqsControlRecord *result);
#ifdef __cplusplus
}
#endif
#endif
