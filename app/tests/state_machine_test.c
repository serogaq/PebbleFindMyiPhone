#include <assert.h>
#include <stdint.h>

#include "state_machine.h"

#define ASSERT_JS_RESULT(name) _Static_assert(RESULT_##name == JS_RESULT_##name, #name)
ASSERT_JS_RESULT(OK);
ASSERT_JS_RESULT(CONFIG_MISSING);
ASSERT_JS_RESULT(CONFIG_INVALID);
ASSERT_JS_RESULT(BACKEND_UNAVAILABLE);
ASSERT_JS_RESULT(API_UNAUTHORIZED);
ASSERT_JS_RESULT(APPLE_AUTH_REQUIRED);
ASSERT_JS_RESULT(TARGET_NOT_FOUND);
ASSERT_JS_RESULT(SOUND_UNAVAILABLE);
ASSERT_JS_RESULT(RATE_LIMITED);
ASSERT_JS_RESULT(DEVICE_LOOKUP_FAILED);
ASSERT_JS_RESULT(OUTCOME_UNKNOWN);
ASSERT_JS_RESULT(APPLE_REQUEST_FAILED);
ASSERT_JS_RESULT(API_ERROR);

int main(void) {
  AppState state;
  uint32_t sequence = 0;
  app_state_init(&state);
  assert(app_state_can_start(&state));
  assert(app_state_begin(&state, REQUEST_PLAY_SOUND, &sequence));
  assert(sequence == 1);
  assert(!app_state_can_start(&state));
  assert(!app_state_begin(&state, REQUEST_CHECK_STATUS, &sequence));

  StateDecision stale =
      app_state_receive(&state, sequence + 1, REQUEST_PLAY_SOUND, RESULT_OK);
  assert(stale.action == STATE_ACTION_NONE);
  assert(state.busy);

  StateDecision success = app_state_receive(&state, sequence, REQUEST_PLAY_SOUND, RESULT_OK);
  assert(success.action == STATE_ACTION_SUCCESS);
  assert(!state.busy);

  assert(app_state_begin(&state, REQUEST_CHECK_STATUS, &sequence));
  StateDecision ready = app_state_receive(&state, sequence, REQUEST_CHECK_STATUS, RESULT_OK);
  assert(ready.action == STATE_ACTION_READY);

  assert(app_state_begin(&state, REQUEST_CHECK_STATUS, &sequence));
  StateDecision error =
      app_state_receive(&state, sequence, REQUEST_CHECK_STATUS, RESULT_APPLE_AUTH_REQUIRED);
  assert(error.action == STATE_ACTION_ERROR);
  assert(error.error == RESULT_APPLE_AUTH_REQUIRED);

  assert(app_state_begin(&state, REQUEST_PLAY_SOUND, &sequence));
  StateDecision dropped = app_state_inbox_dropped(&state);
  assert(dropped.action == STATE_ACTION_ERROR);
  assert(dropped.error == RESULT_OUTCOME_UNKNOWN);

  assert(app_state_begin(&state, REQUEST_CHECK_STATUS, &sequence));
  dropped = app_state_inbox_dropped(&state);
  assert(dropped.error == RESULT_BACKEND_UNAVAILABLE);
  assert(app_state_inbox_dropped(&state).action == STATE_ACTION_NONE);

  state.sequence = UINT32_MAX;
  assert(app_state_begin(&state, REQUEST_CHECK_STATUS, &sequence));
  assert(sequence == 1);
  return 0;
}
