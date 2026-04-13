# String Pot Crank-Drive Kinematics Summary

## Original briefing

You described a **string potentiometer driven by a crank arrangement** with:

- crank pin offset: \(r\)
- distance from crank centre of rotation to the fixed entry point of the string pot: \(l\)

This differs from the classical slider-crank because there is **no fixed-length connecting rod**. Instead:

- the "connecting rod" is effectively the **string itself**
- the string length **changes continuously**
- one end of the string remains at a **fixed point** at the string pot entry

You asked for expressions for the **displacement, velocity, and acceleration** of the string, and then for the specific case:

- \(r = 75\,\text{mm}\)
- \(l = 500\,\text{mm}\)

you asked for:

1. peak velocity as a function of crank RPM
2. the maximum error between the exact displacement and a sinusoidal approximation
3. peak acceleration as a function of RPM, including values at **250 RPM** and **350 RPM**

---

## Geometry and exact string length

Take the crank centre as the origin, and place the fixed string entry point at \((l,0)\). If the crank angle is \(\theta\), then the crank pin position is:

\[
P = (r\cos\theta,\; r\sin\theta)
\]

The fixed string entry point is:

\[
E = (l,0)
\]

The exact string length is the distance from \(P\) to \(E\):

\[
s(\theta) = \sqrt{(l-r\cos\theta)^2 + (r\sin\theta)^2}
\]

which simplifies to:

\[
\boxed{s(\theta)=\sqrt{l^2+r^2-2lr\cos\theta}}
\]

If displacement is measured relative to the minimum string length, then for \(l>r\):

\[
s_{\min}=l-r
\]

so the string displacement is:

\[
\boxed{x(\theta)=s(\theta)-(l-r)}
\]

The maximum string length is:

\[
s_{\max}=l+r
\]

so the total stroke is:

\[
\boxed{s_{\max}-s_{\min}=2r}
\]

---

## Exact velocity

Let crank angular speed be \(\omega=\dot\theta\). Then:

\[
\dot x = \dot s = \frac{ds}{d\theta}\,\dot\theta
\]

Differentiating gives:

\[
\boxed{v(\theta)=\dot x = \frac{lr\,\omega\,\sin\theta}{\sqrt{l^2+r^2-2lr\cos\theta}}}
\]

---

## Exact acceleration

For the general case with angular acceleration \(\alpha = \ddot\theta\):

\[
\ddot x = \ddot s = \frac{lr\sin\theta}{s}\,\alpha + \left(\frac{lr\cos\theta}{s} - \frac{l^2r^2\sin^2\theta}{s^3}\right)\omega^2
\]

where:

\[
s = \sqrt{l^2+r^2-2lr\cos\theta}
\]

For **constant crank speed** (the case used for the peak-acceleration results below), \(\alpha=0\), so:

\[
\boxed{a(\theta)=\ddot x = \left(\frac{lr\cos\theta}{s} - \frac{l^2r^2\sin^2\theta}{s^3}\right)\omega^2}
\]

---

## Special case: \(r=75\,\text{mm},\; l=500\,\text{mm}\)

---

## Peak velocity as a function of crank RPM

Using:

\[
\omega = \frac{2\pi N}{60}
\]

where \(N\) is crank speed in RPM, the exact velocity is:

\[
v(\theta)=\frac{lr\,\omega\,\sin\theta}{\sqrt{l^2+r^2-2lr\cos\theta}}
\]

For \(l>r\), the peak velocity magnitude occurs at:

\[
\cos\theta = \frac{r}{l}
\]

For this geometry:

\[
\cos\theta = \frac{75}{500}=0.15
\quad\Rightarrow\quad
\theta \approx 81.37^\circ
\]

and the peak velocity magnitude simplifies exactly to:

\[
\boxed{|v|_{\max}=r\omega}
\]

Therefore:

\[
\boxed{|v|_{\max}=75\left(\frac{2\pi N}{60}\right)\;\text{mm/s}}
\]

which can be written as:

\[
\boxed{|v|_{\max}=2.5\pi N\;\text{mm/s}}
\]

Numerically:

\[
\boxed{|v|_{\max}\approx 7.854\,N\;\text{mm/s}}
\]

or:

\[
\boxed{|v|_{\max}\approx 0.007854\,N\;\text{m/s}}
\]

Examples:

- 60 RPM -> 471.2 mm/s
- 100 RPM -> 785.4 mm/s
- 120 RPM -> 942.5 mm/s

---

## Sinusoidal displacement approximation and its maximum error

For large \(l/r\), the natural sinusoidal approximation is:

\[
\boxed{x_{\sin}(\theta)=r(1-\cos\theta)}
\]

For this geometry:

\[
\boxed{x_{\sin}(\theta)=75(1-\cos\theta)\;\text{mm}}
\]

The exact-minus-sinusoid error is:

\[
e(\theta)=x(\theta)-x_{\sin}(\theta)
\]

which becomes:

\[
e(\theta)=\sqrt{l^2+r^2-2lr\cos\theta}-l+r\cos\theta
\]

The maximum error occurs at:

\[
\cos\theta = \frac{r}{2l}
\]

For this geometry:

\[
\cos\theta = \frac{75}{1000}=0.075
\quad\Rightarrow\quad
\theta \approx 85.70^\circ
\]

and the maximum error is:

\[
\boxed{e_{\max}=\frac{r^2}{2l}}
\]

So here:

\[
\boxed{e_{\max}=\frac{75^2}{2\cdot 500}=5.625\;\text{mm}}
\]

This means the sinusoidal approximation underestimates the exact displacement by at most:

\[
\boxed{5.625\;\text{mm}}
\]

Equivalent interpretations:

- **3.75% of full stroke** (150 mm)
- **7.5% of half-stroke amplitude** (75 mm)

At the exact mid-stroke point:

\[
x_{\text{exact}}=75\;\text{mm}, \qquad x_{\sin}=69.375\;\text{mm}
\]

so the difference is exactly 5.625 mm.

---

## Peak acceleration as a function of crank RPM

Assuming **constant crank speed**, the exact acceleration is:

\[
a(\theta)=\left(\frac{lr\cos\theta}{s} - \frac{l^2r^2\sin^2\theta}{s^3}\right)\omega^2
\]

For \(l>r\), the **maximum positive acceleration** occurs at \(\theta=0\):

\[
\boxed{a_{\max}=\frac{lr}{l-r}\,\omega^2}
\]

The most negative acceleration occurs at \(\theta=\pi\):

\[
\boxed{a_{\min}=-\frac{lr}{l+r}\,\omega^2}
\]

So the peak magnitude is:

\[
\boxed{|a|_{\text{peak}}=\frac{lr}{l-r}\left(\frac{2\pi N}{60}\right)^2}
\]

For \(r=75\,\text{mm}\), \(l=500\,\text{mm}\):

\[
\frac{lr}{l-r}=\frac{500\cdot 75}{500-75}=88.235294\;\text{mm}
\]

so:

\[
\boxed{|a|_{\text{peak}}=88.235294\left(\frac{2\pi N}{60}\right)^2\;\text{mm/s}^2}
\]

which simplifies numerically to:

\[
\boxed{|a|_{\text{peak}}\approx 0.96761\,N^2\;\text{mm/s}^2}
\]

or:

\[
\boxed{|a|_{\text{peak}}\approx 9.6761\times 10^{-4}\,N^2\;\text{m/s}^2}
\]

### At 250 RPM

\[
|a|_{\text{peak}}\approx 0.96761(250)^2 = 60475.5\;\text{mm/s}^2
\]

\[
\boxed{|a|_{\text{peak}}\approx 60.48\;\text{m/s}^2}
\]

### At 350 RPM

\[
|a|_{\text{peak}}\approx 0.96761(350)^2 = 118532.0\;\text{mm/s}^2
\]

\[
\boxed{|a|_{\text{peak}}\approx 118.53\;\text{m/s}^2}
\]

### Most negative acceleration for completeness

For this geometry:

\[
\frac{lr}{l+r}=\frac{500\cdot 75}{575}=65.21739\;\text{mm}
\]

so:

\[
a_{\min} \approx -0.71519\,N^2\;\text{mm/s}^2
\]

Numerically:

- 250 RPM -> \(-44.70\,\text{m/s}^2\)
- 350 RPM -> \(-87.61\,\text{m/s}^2\)

---

## Final compact results

### Exact kinematics

\[
\boxed{s(\theta)=\sqrt{l^2+r^2-2lr\cos\theta}}
\]

\[
\boxed{x(\theta)=\sqrt{l^2+r^2-2lr\cos\theta}-(l-r)}
\]

\[
\boxed{v(\theta)=\frac{lr\,\omega\,\sin\theta}{\sqrt{l^2+r^2-2lr\cos\theta}}}
\]

\[
\boxed{a(\theta)=\left(\frac{lr\cos\theta}{s}-\frac{l^2r^2\sin^2\theta}{s^3}\right)\omega^2}
\qquad (\text{constant } \omega)
\]

with:

\[
s=\sqrt{l^2+r^2-2lr\cos\theta}
\]

### For \(r=75\,\text{mm},\; l=500\,\text{mm}\)

Peak velocity:

\[
\boxed{|v|_{\max}=2.5\pi N\;\text{mm/s}\approx 7.854N\;\text{mm/s}}
\]

Maximum sinusoid error:

\[
\boxed{e_{\max}=5.625\;\text{mm}}
\]

Peak acceleration:

\[
\boxed{|a|_{\text{peak}}\approx 0.96761N^2\;\text{mm/s}^2}
\]

or:

\[
\boxed{|a|_{\text{peak}}\approx 9.6761\times 10^{-4}N^2\;\text{m/s}^2}
\]

with:

- \(250\,\text{RPM} \rightarrow 60.48\,\text{m/s}^2\)
- \(350\,\text{RPM} \rightarrow 118.53\,\text{m/s}^2\)

