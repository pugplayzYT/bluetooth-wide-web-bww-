#pragma once
#include <cstddef>
namespace bww {
// JSON documents and outbound chunk strings are already allocated by callers.
// Reserve room for stdio/mutexes, plus only a buffer that still needs allocation.
inline bool fileMemoryAvailable(size_t freeBytes, size_t largestBlock, size_t newBufferBytes = 0) {
    return newBufferBytes <= freeBytes && freeBytes - newBufferBytes >= 8192 &&
        largestBlock >= 4096 && largestBlock >= newBufferBytes &&
        (!newBufferBytes || largestBlock - newBufferBytes >= 128);
}
}
