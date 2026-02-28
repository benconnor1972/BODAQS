#pragma once
#include <Arduino.h>
#include <vector>

struct TransformMeta {
  String id;       // stable slug: "wheel_mm"
  String label;    // UI label: "Wheel travel (mm)"
  String inUnits;  // e.g., "counts"
  String outUnits; // e.g., "mm"
  String type;     // "poly" | "lut" | "identity"
};

class OutputTransform {
public:
  virtual ~OutputTransform() {}
  TransformMeta meta;
  virtual float apply(float x) const = 0;
};

class IdentityTransform : public OutputTransform {
public:
  IdentityTransform(const String& in="raw", const String& out="raw") {
    meta.id = "identity"; meta.label = "Identity";
    meta.inUnits = in; meta.outUnits = out; meta.type = "identity";
  }
  float apply(float x) const override { return x; }
};

class PolyTransform : public OutputTransform {
public:
  // y = a0 + a1 x + a2 x^2 + ...
  std::vector<float> a; // a0..aN
  float apply(float x) const override {
    float y = 0.0f;
    for (int i = int(a.size()) - 1; i >= 0; --i) y = y * x + a[(size_t)i];
    return y;
  }
};

class LUTTransform : public OutputTransform {
public:
  struct Node { float x; float y; float slope; }; // slope precomputed
  std::vector<Node> nodes;
  bool clamp = true; // clamp extrapolation by default

  float apply(float x) const override {
    if (nodes.empty()) return x;
    if (x <= nodes.front().x) return clamp ? nodes.front().y : nodes.front().y + nodes.front().slope*(x - nodes.front().x);
    if (x >= nodes.back().x)  return clamp ? nodes.back().y  : nodes.back().y  + nodes.back().slope *(x - nodes.back().x);
    int lo = 0, hi = int(nodes.size()) - 1;
    while (hi - lo > 1) {
      int mid = (lo + hi) >> 1;
      (x < nodes[(size_t)mid].x) ? hi = mid : lo = mid;
    }
    const auto& n = nodes[(size_t)lo];
    return n.y + n.slope * (x - n.x);
  }
};
