# AS5600 string-pot wrap tracking

The firmware unwraps AS5600 string-pot counts before converting them to travel.
The configured `counts_per_turn`, `wrap_threshold_counts`, calibration, and log
column formats are unchanged. No configuration migration is needed.

Analog output can pass through intermediate voltages when it rolls between the
top and bottom of its range. For example, session
`261019_153445_d1d69224e898` contains `4079 -> 2054 -> 38`. Neither individual
step reaches the default 2048-count threshold, so consecutive-sample tracking
misses the turn.

For analog string pots, the tracker now retains the last accepted endpoint when
a rapid step enters the interior of the range. Endpoints occupy the bottom and
top eighth of a turn; a rapid step is at least one quarter of the configured
wrap threshold. It holds unwrapped counts and calibrated displacement for up to
three intermediate samples, then applies the normal wrap comparison against
the retained endpoint. Reaching either endpoint resolves the transition
immediately. At 500 Hz, the maximum hold is 6 ms. The fourth interior sample is
accepted if settling has not completed. Raw wrapped counts are always logged
unchanged, including intermediate samples.

This bounded hold also applies to genuine rapid movement away from an endpoint;
that movement resumes when the hold expires. Gradual motion is unaffected.
Transitions lasting longer than the window or genuine motion exceeding half a
turn within it remain ambiguous; this is not a guarantee of recovery from
arbitrarily filtered signals or acquisition gaps. I2C string pots retain their
existing tracking behavior. Starting a session or reconfiguring a sensor clears
pending transitions.

The focused host tests include forward and reverse recorded failures, direct
crossings, multiple settling samples, reversals, timeout, reset, ordinary
movement, and custom count ranges.
