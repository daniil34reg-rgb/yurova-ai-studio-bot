from aiogram.fsm.state import State, StatesGroup


class PurchaseStates(StatesGroup):
    waiting_screenshot = State()
    waiting_confirm = State()


class GiveawayStates(StatesGroup):
    waiting_phone = State()
    waiting_full_name = State()
    waiting_city = State()
    waiting_custom_sticker_count = State()


class SupportStates(StatesGroup):
    waiting_message = State()


class AdminStates(StatesGroup):
    waiting_broadcast = State()
    waiting_reject_reason = State()
    waiting_ban_id = State()
    waiting_promo_title = State()
    waiting_promo_prize = State()
    waiting_promo_price = State()
    waiting_promo_photo = State()
    waiting_edit_promo_price = State()
    waiting_edit_promo_title = State()
    waiting_edit_promo_prize = State()
    waiting_edit_promo_photo = State()
    waiting_qr_title = State()
    waiting_qr_photo = State()
    waiting_payment_method_title = State()
    waiting_payment_method_link = State()
    waiting_edit_payment_method_title = State()
    waiting_edit_payment_method_qr = State()
    waiting_edit_payment_method_link = State()
    waiting_saved_qr_title = State()
    waiting_saved_qr_photo = State()
    waiting_edit_saved_qr_title = State()
    waiting_edit_saved_qr_photo = State()
    waiting_welcome_text = State()
    waiting_payment_instruction_text = State()
    waiting_bank_choice_text = State()
    waiting_stickers_text = State()
    waiting_payment_manager_username = State()
    waiting_qr_auto_delete_hours = State()
    waiting_main_menu_photo = State()
    waiting_main_join_button_label = State()
    waiting_warning_text = State()
    waiting_post_payment_label = State()
    waiting_post_payment_text = State()
    waiting_edit_promo_desc = State()
    waiting_edit_promo_payment_text = State()
    waiting_btn_label = State()
    waiting_btn_count = State()
    waiting_edit_btn_label = State()
    waiting_edit_btn_count = State()
    waiting_btn_config_title = State()
    waiting_edit_btn_config_title = State()
    waiting_btn_config_button_label = State()
    waiting_btn_config_button_count = State()
    waiting_edit_btn_config_button_label = State()
    waiting_edit_btn_config_button_count = State()
