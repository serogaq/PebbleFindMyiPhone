#include <pebble.h>

#include "localization.auto.h"

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

static Window *s_window;
static TextLayer *s_title_layer;
static TextLayer *s_body_layer;
static TextLayer *s_footer_layer;
static AppTimer *s_animation_timer;
static AppTimer *s_success_timer;
static AppTimer *s_request_timer;
static AppTimer *s_startup_timer;
static uint32_t s_sequence;
static uint32_t s_pending_sequence;
static RequestKind s_pending_kind;
static bool s_busy;
static uint8_t s_animation_step;

static void prv_cancel_timer(AppTimer **timer) {
  if (*timer) {
    app_timer_cancel(*timer);
    *timer = NULL;
  }
}

static void prv_set_screen(const char *title, const char *body, const char *footer) {
  text_layer_set_text(s_title_layer, title);
  text_layer_set_text(s_body_layer, body);
  text_layer_set_text(s_footer_layer, footer);
}

static void prv_show_ready(void) {
  s_busy = false;
  prv_cancel_timer(&s_animation_timer);
  prv_cancel_timer(&s_request_timer);
  prv_set_screen(
      localization_get(WATCH_STRING_APP_TITLE),
      localization_get(WATCH_STRING_READY),
      localization_get(WATCH_STRING_DOUBLE_CLICK_SELECT));
}

static void prv_animation_tick(void *context) {
  static char buffer[32];
  const char *base = s_pending_kind == REQUEST_PLAY_SOUND
                         ? localization_get(WATCH_STRING_SENDING)
                         : localization_get(WATCH_STRING_CHECKING);
  s_animation_step = (s_animation_step + 1) % 4;
  snprintf(buffer, sizeof(buffer), "%s%.*s", base, s_animation_step, "...");
  text_layer_set_text(s_body_layer, buffer);
  s_animation_timer = app_timer_register(350, prv_animation_tick, NULL);
}

static void prv_start_animation(RequestKind kind) {
  s_pending_kind = kind;
  s_animation_step = 0;
  prv_cancel_timer(&s_animation_timer);
  prv_animation_tick(NULL);
}

static void prv_show_error(ResultCode code) {
  const char *body = localization_get(WATCH_STRING_REQUEST_FAILED);
  const char *footer = localization_get(WATCH_STRING_DOUBLE_CLICK_RETRY);

  switch (code) {
    case RESULT_CONFIG_MISSING:
      body = localization_get(WATCH_STRING_SETTINGS_REQUIRED);
      footer = localization_get(WATCH_STRING_OPEN_PEBBLE_SETTINGS);
      break;
    case RESULT_CONFIG_INVALID:
      body = localization_get(WATCH_STRING_INVALID_BACKEND_SETTINGS);
      footer = localization_get(WATCH_STRING_CHECK_ADDRESS_AND_TOKEN);
      break;
    case RESULT_BACKEND_UNAVAILABLE:
      body = localization_get(WATCH_STRING_BACKEND_UNAVAILABLE);
      break;
    case RESULT_API_UNAUTHORIZED:
      body = localization_get(WATCH_STRING_INVALID_BACKEND_TOKEN);
      footer = localization_get(WATCH_STRING_UPDATE_APP_SETTINGS);
      break;
    case RESULT_APPLE_AUTH_REQUIRED:
      body = localization_get(WATCH_STRING_APPLE_SIGN_IN_REQUIRED);
      footer = localization_get(WATCH_STRING_RUN_AUTH_LOGIN);
      break;
    case RESULT_TARGET_NOT_FOUND:
      body = localization_get(WATCH_STRING_IPHONE_NOT_FOUND);
      footer = localization_get(WATCH_STRING_CHECK_SERVER_TARGET_ID);
      break;
    case RESULT_SOUND_UNAVAILABLE:
      body = localization_get(WATCH_STRING_PLAY_SOUND_UNAVAILABLE);
      break;
    case RESULT_RATE_LIMITED:
      body = localization_get(WATCH_STRING_PLEASE_WAIT);
      footer = localization_get(WATCH_STRING_TRIGGERED_TOO_RECENTLY);
      break;
    case RESULT_DEVICE_LOOKUP_FAILED:
      body = localization_get(WATCH_STRING_APPLE_LOOKUP_FAILED);
      break;
    case RESULT_OUTCOME_UNKNOWN:
      body = localization_get(WATCH_STRING_RESULT_UNKNOWN);
      footer = localization_get(WATCH_STRING_SOUND_MAY_HAVE_STARTED);
      break;
    case RESULT_APPLE_REQUEST_FAILED:
      body = localization_get(WATCH_STRING_APPLE_REQUEST_FAILED);
      break;
    case RESULT_API_ERROR:
    default:
      break;
  }

  s_busy = false;
  prv_cancel_timer(&s_animation_timer);
  prv_cancel_timer(&s_request_timer);
  prv_set_screen(localization_get(WATCH_STRING_APP_TITLE), body, footer);
  vibes_double_pulse();
}

static void prv_success_timeout(void *context) {
  s_success_timer = NULL;
  prv_show_ready();
}

static void prv_show_success(void) {
  s_busy = false;
  prv_cancel_timer(&s_animation_timer);
  prv_cancel_timer(&s_request_timer);
  prv_cancel_timer(&s_success_timer);
  prv_set_screen(
      localization_get(WATCH_STRING_APP_TITLE),
      localization_get(WATCH_STRING_COMMAND_SENT),
      localization_get(WATCH_STRING_LISTEN_FOR_FIND_MY_ALERT));
  vibes_short_pulse();
  s_success_timer = app_timer_register(3500, prv_success_timeout, NULL);
}

static void prv_request_timeout(void *context) {
  s_request_timer = NULL;
  prv_show_error((ResultCode)(uintptr_t)context);
}

static void prv_send_request(RequestKind kind) {
  if (s_busy) {
    return;
  }

  DictionaryIterator *iterator = NULL;
  AppMessageResult begin_result = app_message_outbox_begin(&iterator);
  if (begin_result != APP_MSG_OK || !iterator) {
    prv_show_error(RESULT_BACKEND_UNAVAILABLE);
    return;
  }

  s_sequence++;
  if (s_sequence == 0) {
    s_sequence = 1;
  }
  s_pending_sequence = s_sequence;
  s_pending_kind = kind;
  s_busy = true;
  dict_write_uint8(iterator, MESSAGE_KEY_REQUEST_KIND, (uint8_t)kind);
  dict_write_uint32(iterator, MESSAGE_KEY_REQUEST_SEQ, s_pending_sequence);
  dict_write_end(iterator);

  prv_start_animation(kind);
  if (app_message_outbox_send() != APP_MSG_OK) {
    prv_show_error(RESULT_BACKEND_UNAVAILABLE);
    return;
  }
  prv_cancel_timer(&s_request_timer);
  s_request_timer = app_timer_register(
      kind == REQUEST_PLAY_SOUND ? 50000 : 12000,
      prv_request_timeout,
      (void *)(uintptr_t)(kind == REQUEST_PLAY_SOUND ? RESULT_OUTCOME_UNKNOWN
                                                     : RESULT_BACKEND_UNAVAILABLE));
}

static void prv_startup_request(void *context) {
  s_startup_timer = NULL;
  // A user can double-click before the cold-start health timer fires. Never
  // replace an in-flight Play Sound sequence with the background health check.
  if (!s_busy) {
    prv_send_request(REQUEST_CHECK_STATUS);
  }
}

static void prv_select_multi_click_handler(ClickRecognizerRef recognizer, void *context) {
  if (!s_busy) {
    prv_cancel_timer(&s_success_timer);
    prv_send_request(REQUEST_PLAY_SOUND);
  }
}

static void prv_click_config_provider(void *context) {
  window_multi_click_subscribe(BUTTON_ID_SELECT, 2, 2, 300, true,
                               prv_select_multi_click_handler);
}

static void prv_inbox_received(DictionaryIterator *iterator, void *context) {
  Tuple *sequence_tuple = dict_find(iterator, MESSAGE_KEY_REQUEST_SEQ);
  Tuple *kind_tuple = dict_find(iterator, MESSAGE_KEY_RESPONSE_KIND);
  Tuple *result_tuple = dict_find(iterator, MESSAGE_KEY_RESULT_CODE);
  if (!sequence_tuple || !kind_tuple || !result_tuple) {
    return;
  }

  uint32_t sequence = sequence_tuple->value->uint32;
  int32_t kind_value = kind_tuple->value->int32;
  int32_t result_value = result_tuple->value->int32;
  if (kind_value < REQUEST_CHECK_STATUS || kind_value > REQUEST_PLAY_SOUND ||
      result_value < RESULT_OK || result_value > RESULT_API_ERROR) {
    APP_LOG(APP_LOG_LEVEL_WARNING, "Invalid AppMessage response values");
    return;
  }

  RequestKind kind = (RequestKind)kind_value;
  ResultCode result = (ResultCode)result_value;
  if (sequence != s_pending_sequence || kind != s_pending_kind) {
    return;
  }

  if (result == RESULT_OK) {
    if (kind == REQUEST_PLAY_SOUND) {
      prv_show_success();
    } else {
      prv_show_ready();
    }
  } else {
    prv_show_error(result);
  }
}

static void prv_outbox_failed(DictionaryIterator *iterator, AppMessageResult reason,
                              void *context) {
  APP_LOG(APP_LOG_LEVEL_WARNING, "AppMessage outbox failed: %d", (int)reason);
  prv_show_error(RESULT_BACKEND_UNAVAILABLE);
}

static void prv_inbox_dropped(AppMessageResult reason, void *context) {
  APP_LOG(APP_LOG_LEVEL_WARNING, "AppMessage inbox dropped: %d", (int)reason);
  if (s_busy) {
    // A dropped Play Sound response may have followed a successfully dispatched
    // HTTP request, so presenting it as safely retryable would be dangerous.
    prv_show_error(s_pending_kind == REQUEST_PLAY_SOUND ? RESULT_OUTCOME_UNKNOWN
                                                        : RESULT_BACKEND_UNAVAILABLE);
  }
}

static void prv_window_load(Window *window) {
  Layer *window_layer = window_get_root_layer(window);
  GRect bounds = layer_get_bounds(window_layer);
  int16_t side_inset = PBL_IF_ROUND_ELSE(20, 8);
  int16_t top = PBL_IF_ROUND_ELSE(24, 8);
  int16_t width = bounds.size.w - 2 * side_inset;
  int16_t footer_height = PBL_IF_ROUND_ELSE(42, 40);
  int16_t footer_top = bounds.size.h - PBL_IF_ROUND_ELSE(55, 48);
  int16_t body_height = 64;
  int16_t body_area_top = top + 28;
  int16_t body_top = body_area_top + (footer_top - body_area_top - body_height) / 2;

  s_title_layer = text_layer_create(GRect(side_inset, top, width, 28));
  text_layer_set_background_color(s_title_layer, GColorClear);
  text_layer_set_text_color(s_title_layer, PBL_IF_COLOR_ELSE(GColorPictonBlue, GColorBlack));
  text_layer_set_font(s_title_layer, fonts_get_system_font(FONT_KEY_GOTHIC_18_BOLD));
  text_layer_set_text_alignment(s_title_layer, GTextAlignmentCenter);

  s_body_layer = text_layer_create(GRect(side_inset, body_top, width, body_height));
  text_layer_set_background_color(s_body_layer, GColorClear);
  text_layer_set_font(s_body_layer, fonts_get_system_font(FONT_KEY_GOTHIC_24_BOLD));
  text_layer_set_text_alignment(s_body_layer, GTextAlignmentCenter);
  text_layer_set_overflow_mode(s_body_layer, GTextOverflowModeWordWrap);

  s_footer_layer =
      text_layer_create(GRect(side_inset, footer_top, width, footer_height));
  text_layer_set_background_color(s_footer_layer, GColorClear);
  text_layer_set_font(s_footer_layer, fonts_get_system_font(FONT_KEY_GOTHIC_14));
  text_layer_set_text_alignment(s_footer_layer, GTextAlignmentCenter);
  text_layer_set_overflow_mode(s_footer_layer, GTextOverflowModeWordWrap);

  layer_add_child(window_layer, text_layer_get_layer(s_title_layer));
  layer_add_child(window_layer, text_layer_get_layer(s_body_layer));
  layer_add_child(window_layer, text_layer_get_layer(s_footer_layer));

  prv_set_screen(
      localization_get(WATCH_STRING_APP_TITLE),
      localization_get(WATCH_STRING_STARTING),
      localization_get(WATCH_STRING_CHECKING_BACKEND));
}

static void prv_window_unload(Window *window) {
  text_layer_destroy(s_footer_layer);
  text_layer_destroy(s_body_layer);
  text_layer_destroy(s_title_layer);
}

static void prv_init(void) {
  localization_init(i18n_get_system_locale());

  s_window = window_create();
  window_set_background_color(s_window, GColorWhite);
  window_set_click_config_provider(s_window, prv_click_config_provider);
  window_set_window_handlers(s_window, (WindowHandlers){
      .load = prv_window_load,
      .unload = prv_window_unload,
  });
  window_stack_push(s_window, true);

  app_message_register_inbox_received(prv_inbox_received);
  app_message_register_inbox_dropped(prv_inbox_dropped);
  app_message_register_outbox_failed(prv_outbox_failed);
  const uint32_t inbox_size =
      dict_calc_buffer_size(3, sizeof(int32_t), sizeof(int32_t), sizeof(int32_t));
  const uint32_t outbox_size =
      dict_calc_buffer_size(2, sizeof(uint8_t), sizeof(uint32_t));
  AppMessageResult open_result = app_message_open(inbox_size, outbox_size);
  if (open_result != APP_MSG_OK) {
    APP_LOG(APP_LOG_LEVEL_ERROR, "AppMessage open failed: %d", (int)open_result);
    prv_show_error(RESULT_BACKEND_UNAVAILABLE);
    return;
  }
  // Give the mobile app time to start this watchapp's PKJS session after a
  // cold launch. The request watchdog still handles a lost companion message.
  s_startup_timer = app_timer_register(1000, prv_startup_request, NULL);
}

static void prv_deinit(void) {
  prv_cancel_timer(&s_animation_timer);
  prv_cancel_timer(&s_success_timer);
  prv_cancel_timer(&s_request_timer);
  prv_cancel_timer(&s_startup_timer);
  app_message_deregister_callbacks();
  window_destroy(s_window);
}

int main(void) {
  prv_init();
  app_event_loop();
  prv_deinit();
}
