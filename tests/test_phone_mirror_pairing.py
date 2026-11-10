"""Pure pairing helpers: secrets, QR payload, expiry, mDNS parser (R2.1-R2.7)."""

import re
import secrets

import pytest
from src.widgets import phone_mirror_pairing as pairing
from src.widgets import phone_mirror_runner as runner

# Real `adb mdns services` output (Pixel 10, adb 37), TAB-separated.
MDNS_WIRELESS_SCREEN = (
    "List of discovered mdns services\n"
    "adb-56201FDCR0077W-I7p3gg\t_adb-tls-connect._tcp\t192.168.1.134:45135\n"
)
MDNS_PAIRING_DIALOG = (
    "List of discovered mdns services\n"
    "adb-56201FDCR0077W-I7p3gg\t_adb-tls-pairing._tcp\t192.168.1.134:35715\n"
    "adb-56201FDCR0077W-I7p3gg\t_adb-tls-connect._tcp\t192.168.1.134:45135\n"
)
# The QR flow: the phone advertises the pairing entry under OUR name, while the
# connect entry keeps the device's own `adb-<serial>-<rand>` name.
MDNS_QR_FLOW = (
    "List of discovered mdns services\n"
    "qtile-Ab3dE5gH7k\t_adb-tls-pairing._tcp\t192.168.1.134:35715\n"
    "adb-56201FDCR0077W-I7p3gg\t_adb-tls-connect._tcp\t192.168.1.134:45135\n"
)

PAYLOAD = re.compile(r"^WIFI:T:ADB;S:[^;]+;P:[^;]+;;$")


# --- R2.1: QR payload ---------------------------------------------------------


def test_new_session_payload_matches_the_adb_qr_format() -> None:
    session = pairing.new_session(now=0.0)

    assert PAYLOAD.match(session.payload)
    assert session.payload == f"WIFI:T:ADB;S:{session.name};P:{session.password};;"


def test_each_session_has_its_own_name_and_password() -> None:
    first = pairing.new_session(now=0.0)
    second = pairing.new_session(now=0.0)

    assert first.name != second.name
    assert first.password != second.password


def test_name_and_password_have_the_designed_shape() -> None:
    session = pairing.new_session(now=0.0)

    assert re.fullmatch(r"qtile-[A-Za-z0-9]{10}", session.name)
    assert re.fullmatch(r"[A-Za-z0-9]{12}", session.password)
    assert len(session.password) >= 8


def test_secrets_come_from_the_secrets_module(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_choice(alphabet: str) -> str:
        calls.append(len(alphabet))
        return "x"

    monkeypatch.setattr(pairing.secrets, "choice", fake_choice)
    session = pairing.new_session(now=0.0)

    assert session.name == "qtile-" + "x" * 10
    assert session.password == "x" * 12
    assert len(calls) == 22
    assert pairing.secrets is secrets


# --- R2.6: expiry, countdown, single use --------------------------------------


def test_session_expires_after_the_ttl() -> None:
    session = pairing.new_session(now=100.0, ttl=180.0)

    assert not session.expired(100.0 + 179.0)
    assert session.expired(100.0 + 181.0)
    assert session.expired(100.0 + 180.0)


def test_default_ttl_is_three_minutes() -> None:
    session = pairing.new_session(now=0.0)

    assert session.ttl == 180.0
    assert session.remaining(0.0) == 180.0


@pytest.mark.parametrize(
    ("elapsed", "text"),
    [
        (0.0, "03:00"),
        (60.0, "02:00"),
        (60.5, "02:00"),
        (179.0, "00:01"),
        (500.0, "00:00"),
    ],
)
def test_countdown_shows_the_remaining_time(elapsed: float, text: str) -> None:
    session = pairing.new_session(now=10.0, ttl=180.0)

    assert session.countdown(10.0 + elapsed) == text


def test_an_expired_session_cannot_be_consumed() -> None:
    session = pairing.new_session(now=0.0, ttl=180.0)

    assert session.consume(181.0) is False


def test_a_session_is_single_use() -> None:
    session = pairing.new_session(now=0.0)

    assert session.consume(5.0) is True
    assert session.consume(6.0) is False


# --- R2.3: mDNS parser ---------------------------------------------------------


def test_parse_mdns_reads_every_real_line() -> None:
    entries = pairing.parse_mdns(MDNS_PAIRING_DIALOG)

    assert [(e.instance, e.service, e.address) for e in entries] == [
        (
            "adb-56201FDCR0077W-I7p3gg",
            "_adb-tls-pairing._tcp",
            "192.168.1.134:35715",
        ),
        (
            "adb-56201FDCR0077W-I7p3gg",
            "_adb-tls-connect._tcp",
            "192.168.1.134:45135",
        ),
    ]


def test_parse_mdns_splits_host_and_port() -> None:
    entry = pairing.parse_mdns(MDNS_WIRELESS_SCREEN)[0]

    assert (entry.host, entry.port) == ("192.168.1.134", 45135)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "List of discovered mdns services\n",
        "* daemon not running; starting now at tcp:5037\n",
        "garbage line without tabs\n",
        "a\tb\n",
        "a\t_adb-tls-connect._tcp\tnot-an-address\n",
        "a\t_adb-tls-connect._tcp\t10.0.0.1:99999\n",
        "a\tnotaservice\t10.0.0.1:5555\n",
        "a\t_adb-tls-connect._tcp\t10.0.0.1:5555\textra\n",
    ],
)
def test_parse_mdns_skips_header_and_junk(text: str) -> None:
    assert pairing.parse_mdns(text) == []


def test_parse_mdns_keeps_good_lines_around_junk() -> None:
    text = "* daemon started\n" + MDNS_PAIRING_DIALOG + "junk\n"

    assert len(pairing.parse_mdns(text)) == 2


def test_find_pairing_matches_our_instance_name() -> None:
    entries = pairing.parse_mdns(MDNS_QR_FLOW)

    found = pairing.find_pairing(entries, "qtile-Ab3dE5gH7k")

    assert found is not None
    assert found.address == "192.168.1.134:35715"


def test_find_pairing_ignores_other_instance_names() -> None:
    entries = pairing.parse_mdns(MDNS_PAIRING_DIALOG)

    assert pairing.find_pairing(entries, "qtile-Ab3dE5gH7k") is None


def test_find_pairing_does_not_return_connect_entries() -> None:
    entries = pairing.parse_mdns(MDNS_WIRELESS_SCREEN)

    assert pairing.find_pairing(entries, "adb-56201FDCR0077W-I7p3gg") is None


def test_find_connect_matches_by_host_not_by_instance_name() -> None:
    entries = pairing.parse_mdns(MDNS_QR_FLOW)

    found = pairing.find_connect(entries, "192.168.1.134")

    assert found is not None
    assert found.address == "192.168.1.134:45135"
    assert found.instance != "qtile-Ab3dE5gH7k"


def test_find_connect_ignores_other_hosts_and_pairing_entries() -> None:
    entries = pairing.parse_mdns(MDNS_QR_FLOW)

    assert pairing.find_connect(entries, "192.168.1.200") is None
    only_pairing = [e for e in entries if e.service == pairing.PAIRING_SERVICE]
    assert pairing.find_connect(only_pairing, "192.168.1.134") is None


# --- R2.7: manual input --------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["192.168.1.20:37000", "10.0.0.5:1", " 192.168.1.20:37000 ", "phone.lan:65535"],
)
def test_parse_endpoint_accepts_host_and_port(text: str) -> None:
    assert pairing.parse_endpoint(text) == text.strip()


@pytest.mark.parametrize(
    "text",
    [
        "",
        "192.168.1.20",
        "192.168.1.20:",
        "192.168.1.20:0",
        "192.168.1.20:70000",
        "192.168.1.20:12ab",
        "-s:5555",
        "a b:5555",
        "host;rm:5555",
        "192.168.1.20:5555 extra",
    ],
)
def test_parse_endpoint_rejects_malformed_input(text: str) -> None:
    assert pairing.parse_endpoint(text) is None


@pytest.mark.parametrize("code", ["123456", " 654321 ", "000000"])
def test_parse_code_accepts_six_digits(code: str) -> None:
    assert pairing.parse_code(code) == code.strip()


@pytest.mark.parametrize("code", ["", "12345", "1234567", "12345a", "12 456", "--help"])
def test_parse_code_rejects_everything_else(code: str) -> None:
    assert pairing.parse_code(code) is None


def test_manual_form_is_accepted_by_the_runner_validation() -> None:
    argv = pairing.build_zenity_pair_argv()

    runner.validate(argv)
    assert argv[:2] == ["zenity", "--forms"]
    assert sum(arg.startswith("--add-entry=") for arg in argv) == 2


def test_manual_form_output_is_parsed_into_endpoint_and_code() -> None:
    assert pairing.parse_zenity_pair("192.168.1.20:37000|123456\n") == (
        "192.168.1.20:37000",
        "123456",
    )


@pytest.mark.parametrize(
    "stdout",
    ["", "192.168.1.20:37000", "bad|123456", "192.168.1.20:37000|12", "a|b|c"],
)
def test_manual_form_rejects_malformed_output(stdout: str) -> None:
    assert pairing.parse_zenity_pair(stdout) is None


# --- argv builders and redaction ----------------------------------------------


def test_pair_argv_never_carries_the_code() -> None:
    argv = pairing.build_pair_argv("adb", "192.168.1.20:37000")

    assert argv == ["adb", "pair", "192.168.1.20:37000"]
    runner.validate(argv)


def test_mdns_argv_only_asks_for_services_or_check() -> None:
    assert pairing.build_mdns_argv("adb", "services") == ["adb", "mdns", "services"]
    assert pairing.build_mdns_argv("adb", "check") == ["adb", "mdns", "check"]
    runner.validate(pairing.build_mdns_argv("adb", "services"))


def test_redact_removes_the_secret_everywhere() -> None:
    text = "pair secretvalue12 -> secretvalue12 done"

    assert pairing.redact(text, "secretvalue12") == "pair *** -> *** done"


def test_redact_with_an_empty_secret_changes_nothing() -> None:
    assert pairing.redact("plain text", "") == "plain text"
