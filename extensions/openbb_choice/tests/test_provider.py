from openbb_choice.provider import provider


def test_provider_registration():
    assert provider.name == "choice"
    assert provider.credentials == ["choice_username", "choice_password"]
    assert set(provider.fetcher_dict) == {"EquityHistorical"}
