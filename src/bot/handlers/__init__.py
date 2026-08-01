from aiogram import Router
from .start import router as start_router
from .payment import router as payment_router
from .admin import router as admin_router


def setup_routers() -> Router:
    main_router = Router()
    main_router.include_router(start_router)
    main_router.include_router(payment_router)
    main_router.include_router(admin_router)
    return main_router
