# https://github.com/BroHui/python-yeast
#
# MIT License
#
# Copyright (c) 2018 Hui
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import math
import time

alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_'
length = 64
t_map = {}
seed = 0
i = 0
prev = None

for i in range(length):
    t_map[alphabet[i]] = i


def encode(num):
    encoded = ''
    while True:
        encoded = alphabet[int(num % length)] + encoded
        num = math.floor(num / length)
        # simulate do-while
        if not (num > 0):
            break
    return encoded


def decode(enc_str):
    decoded = 0
    for i in range(len(enc_str)):
        decoded = decoded * length + t_map[enc_str[i]]
    return decoded


def yeast():
    global prev, seed
    ts = int(time.time() * 1000)
    now = encode(ts)
    if now != prev:
        seed = 0
        prev = now
        return now
    else:
        r = now + '.' + encode(seed)
        seed += 1
        return r


if __name__ == '__main__':
    print(yeast())
