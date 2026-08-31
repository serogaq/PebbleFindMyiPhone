#pragma once

#include <stdbool.h>
#include <stdint.h>

typedef enum {
  REQUEST_CHECK_STATUS = 1,
  REQUEST_PLAY_SOUND = 2,
} RequestKind;

typedef enum {
  RESULT_OK = 0,
  RESULT_CONFIG_MISSING = 1,
  RESULT_CONFIG_INVALID = 2,
  RESULT_BACKEND_UNAVAILABLE = 3,
  RESULT_API_UNAUTHORIZED = 4,
  RESULT_APPLE_AUTH_REQUIRED = 5,
  RESULT_TARGET_NOT_FOUND = 6,
  RESULT_SOUND_UNAVAILABLE = 7,
  RESULT_RATE_LIMITED = 8,
  RESULT_DEVICE_LOOKUP_FAILED = 9,
  RESULT_OUTCOME_UNKNOWN = 10,
  RESULT_APPLE_REQUEST_FAILED = 11,
  RESULT_API_ERROR = 12,
} ResultCode;

typedef enum {
  STATE_ACTION_NONE = 0,
  STATE_ACTION_READY,
  STATE_ACTION_SUCCESS,
  STATE_ACTION_ERROR,
} StateAction;

typedef struct {
  uint32_t sequence;
  uint32_t pending_sequence;
  RequestKind pending_kind;
  bool busy;
} AppState;

typedef struct {
  StateAction action;
  ResultCode error;
} StateDecision;

void app_state_init(AppState *state);
bool app_state_can_start(const AppState *state);
bool app_state_begin(AppState *state, RequestKind kind, uint32_t *sequence);
void app_state_finish(AppState *state);
StateDecision app_state_receive(AppState *state, uint32_t sequence, int32_t kind,
                                int32_t result);
StateDecision app_state_inbox_dropped(AppState *state);
