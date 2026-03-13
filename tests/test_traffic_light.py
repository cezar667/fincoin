from app.domain.services.traffic_light import TrafficLight, classify_balance


def test_traffic_light_green() -> None:
    assert classify_balance(0, 100_00) == TrafficLight.GREEN


def test_traffic_light_yellow() -> None:
    assert classify_balance(-50_00, 100_00) == TrafficLight.YELLOW


def test_traffic_light_red() -> None:
    assert classify_balance(-150_00, 100_00) == TrafficLight.RED

