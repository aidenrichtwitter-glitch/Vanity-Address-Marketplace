from core.words import get_valid_words, UPPERCASE_BASE58

TAIL_SIZE = 6


class WordFilter:
    def __init__(self, min_length=3, max_length=0, custom_words=None):
        self.min_length = min_length
        self.max_length = max_length
        self.tail_size = TAIL_SIZE

        self.words = get_valid_words(
            min_length=min_length,
            max_length=max_length,
            custom_words=custom_words,
        )
        self._build_lookup()

    def _build_lookup(self):
        self.by_length = {}
        for w in self.words:
            wlen = len(w)
            if wlen not in self.by_length:
                self.by_length[wlen] = set()
            self.by_length[wlen].add(w)

    def check_address(self, address):
        for wlen in sorted(self.by_length.keys(), reverse=True):
            if wlen > len(address):
                continue

            tail = address[-wlen:]

            if tail not in self.by_length[wlen]:
                continue

            if wlen >= self.tail_size:
                return tail, ""

            needed_pad = self.tail_size - wlen
            pad_start = len(address) - wlen - needed_pad
            if pad_start < 0:
                continue
            padding = address[pad_start : len(address) - wlen]
            if len(padding) == needed_pad and all(c in UPPERCASE_BASE58 for c in padding):
                return tail, padding

        return None, None

    def score(self, word, padding):
        if not word:
            return 0
        s = len(word) ** 2
        if padding:
            s += len(padding) * 3
        return s
