from src.words import get_valid_words


class WordFilter:
    def __init__(self, min_length=3, max_length=0, custom_words=None, case_sensitive=True):
        self.case_sensitive = case_sensitive
        self.min_length = min_length
        self.max_length = max_length

        words = get_valid_words()

        if custom_words:
            words = list(set(words + custom_words))

        if min_length > 0:
            words = [w for w in words if len(w) >= min_length]
        if max_length > 0:
            words = [w for w in words if len(w) <= max_length]

        if not case_sensitive:
            self.words = sorted(set(w.lower() for w in words), key=lambda w: (-len(w), w))
        else:
            self.words = sorted(words, key=lambda w: (-len(w), w))

        self._build_lookup()

    def _build_lookup(self):
        self.word_set = set(self.words)
        self.by_length = {}
        for w in self.words:
            length = len(w)
            if length not in self.by_length:
                self.by_length[length] = set()
            self.by_length[length].add(w)

    def find_words(self, address):
        found = []
        check_addr = address if self.case_sensitive else address.lower()

        for length in sorted(self.by_length.keys(), reverse=True):
            word_set = self.by_length[length]
            for i in range(len(check_addr) - length + 1):
                substr = check_addr[i : i + length]
                if substr in word_set:
                    found.append((substr, i))

        seen = set()
        unique = []
        for word, pos in found:
            if word not in seen:
                seen.add(word)
                unique.append(word)

        return unique

    def has_any_word(self, address):
        check_addr = address if self.case_sensitive else address.lower()

        for length in sorted(self.by_length.keys(), reverse=True):
            word_set = self.by_length[length]
            for i in range(len(check_addr) - length + 1):
                substr = check_addr[i : i + length]
                if substr in word_set:
                    return True
        return False

    def score_address(self, address):
        words = self.find_words(address)
        if not words:
            return 0
        score = 0
        for word in words:
            score += len(word) ** 2
        return score
