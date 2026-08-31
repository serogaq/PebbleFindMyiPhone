#include "state_machine.h"

static StateDecision prv_none(void) {
  return (StateDecision){.action = STATE_ACTION_NONE, .error = RESULT_OK};
}

void app_state_init(AppState *state) {
  *state = (AppState){0};
}

bool app_state_can_start(const AppState *state) {
  return !state->busy;
}

bool app_state_begin(AppState *state, RequestKind kind, uint32_t *sequence) {
  if (!app_state_can_start(state) || kind < REQUEST_CHECK_STATUS || kind > REQUEST_PLAY_SOUND) {
    return false;
  }
  state->sequence++;
  if (state->sequence == 0) {
    state->sequence = 1;
  }
  state->pending_sequence = state->sequence;
  state->pending_kind = kind;
  state->busy = true;
  *sequence = state->pending_sequence;
  return true;
}

void app_state_finish(AppState *state) {
  state->busy = false;
}

StateDecision app_state_receive(AppState *state, uint32_t sequence, int32_t kind,
                                int32_t result) {
  if (!state->busy || kind < REQUEST_CHECK_STATUS || kind > REQUEST_PLAY_SOUND ||
      result < RESULT_OK || result > RESULT_API_ERROR ||
      sequence != state->pending_sequence || (RequestKind)kind != state->pending_kind) {
    return prv_none();
  }
  app_state_finish(state);
  if (result != RESULT_OK) {
    return (StateDecision){.action = STATE_ACTION_ERROR, .error = (ResultCode)result};
  }
  return (StateDecision){
      .action = kind == REQUEST_PLAY_SOUND ? STATE_ACTION_SUCCESS : STATE_ACTION_READY,
      .error = RESULT_OK,
  };
}

StateDecision app_state_inbox_dropped(AppState *state) {
  if (!state->busy) {
    return prv_none();
  }
  ResultCode error = state->pending_kind == REQUEST_PLAY_SOUND
                         ? RESULT_OUTCOME_UNKNOWN
                         : RESULT_BACKEND_UNAVAILABLE;
  app_state_finish(state);
  return (StateDecision){.action = STATE_ACTION_ERROR, .error = error};
}
