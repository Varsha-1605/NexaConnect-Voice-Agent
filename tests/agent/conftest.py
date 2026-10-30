import pytest

from workflows import CallState


class FakeSpeech:
    def add_done_callback(self, callback):
        callback(self)  # the line has "finished playing" at once


class FakeSession:
    def __init__(self, events):
        self.events = events
        self.said = []

    def say(self, text, **kwargs):
        self.said.append(text)
        self.events.append(("say", text))
        return FakeSpeech()


class FakeContext:
    def __init__(self, **state):
        self.userdata = CallState(**state)
        self.events = []  # ("save", ...) and ("say", ...) in the order they happened
        self.session = FakeSession(self.events)

    def disallow_interruptions(self):
        pass


@pytest.fixture
def context():
    return FakeContext()
