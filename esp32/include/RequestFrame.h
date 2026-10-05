#pragma once
#include "BwwConfig.h"
// Source.read() blocks until a byte, disconnect, or deadline. JSON never crosses a line boundary.
template<class Source>
class RequestFrame {
    Source& source_;
    size_t bytes_ = 0;
    bool ended_ = false;
public:
    bool tooLarge = false;
    explicit RequestFrame(Source& source) : source_(source) {}
    int read() {
        if (ended_) return -1;
        int c = source_.read();
        if (c < 0) return -1;
        if (c == '\n') { ended_ = true; return -1; }
        if (++bytes_ > bww::MAX_WIRE_BYTES) { tooLarge = true; return -1; }
        return c;
    }
    size_t readBytes(char* buffer, size_t count) { size_t i = 0; int c; while (i < count && (c = read()) >= 0) buffer[i++] = c; return i; }
    bool finish() {
        bool clean = true; int c;
        while (!tooLarge && (c = read()) >= 0) if (c != ' ' && c != '\t' && c != '\r') clean = false;
        return ended_ && clean && !tooLarge;
    }
    bool complete() const { return ended_; }
};
