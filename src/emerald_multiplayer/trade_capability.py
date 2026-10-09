"""Local prerequisites for public native effects; host policy is negotiated separately."""


def native_effects_available(companion):
    config, bridge = companion.config, getattr(companion, "_bridge", None)
    return (getattr(config, "menu_abi_version", 0) == 2
        and all(getattr(config, name, 0) == 1 for name in
            ("trade_effect_prepare_abi_version", "trade_effect_save_abi_version", "trade_effect_choice_abi_version"))
        and bridge is not None and all(getattr(bridge, name, False) for name in
            ("save_capable", "window_capable", "trade_effect_prepare_capable", "trade_effect_save_capable", "trade_effect_choice_capable")))
