"""Fixtures for the Phase 6 colour suites: synthetic art built in memory (no network, no files)."""
from __future__ import annotations

import numpy as np
import pytest

SKY, GRASS, SKIN, CLOUD = (90, 170, 230), (70, 150, 60), (224, 172, 105), (250, 250, 250)


@pytest.fixture(scope="session")
def scene_art():
    """400x300 RGB art: 60 % sky, 25 % grass, 10 % skin (a character), 5 % white cloud."""
    img = np.zeros((300, 400, 3), np.uint8)
    img[:] = SKY
    img[225:, :] = GRASS                      # 75/300 = 25 %
    img[105:225, 100:200] = SKIN               # 120x100 = 12000 = 10 %
    img[20:50, 250:450] = CLOUD                # 30x150 = 4500 → 3.75 % (sky reduced accordingly)
    mask = np.zeros((300, 400), bool)
    mask[105:225, 100:200] = True
    return img, mask


@pytest.fixture(scope="session")
def neon_art():
    img = np.zeros((200, 200, 3), np.uint8)
    img[:] = (240, 236, 228)
    img[:, :60] = (57, 255, 20)   # neon green 30 %
    return img


@pytest.fixture(scope="session")
def muted_art():
    img = np.zeros((200, 200, 3), np.uint8)
    img[:] = (233, 216, 184)
    img[:, :60] = (42, 157, 143)
    img[150:, :] = (38, 70, 83)
    return img
