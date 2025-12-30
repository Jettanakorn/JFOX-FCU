//! PID controller implementation for stabilization

#[derive(Clone, Copy, Debug)]
pub struct PidController {
    kp: f32,
    ki: f32,
    kd: f32,
    integral: f32,
    prev_error: f32,
    output_limit: f32,
    integral_limit: f32,
}

impl PidController {
    /// Create new PID controller
    ///
    /// # Arguments
    ///
    /// * `kp` - Proportional gain
    /// * `ki` - Integral gain
    /// * `kd` - Derivative gain
    /// * `output_limit` - Maximum output value (±limit)
    pub fn new(kp: f32, ki: f32, kd: f32, output_limit: f32) -> Self {
        Self {
            kp,
            ki,
            kd,
            integral: 0.0,
            prev_error: 0.0,
            output_limit,
            integral_limit: output_limit * 0.5, // Prevent integral windup
        }
    }

    /// Update PID controller with new error
    ///
    /// # Arguments
    ///
    /// * `error` - Current error (setpoint - measurement)
    /// * `dt` - Time step in seconds
    ///
    /// # Returns
    ///
    /// Control output (limited to ±output_limit)
    pub fn update(&mut self, error: f32, dt: f32) -> f32 {
        // Proportional term
        let p_term = self.kp * error;

        // Integral term with anti-windup
        self.integral += error * dt;
        self.integral = self.integral.clamp(-self.integral_limit, self.integral_limit);
        let i_term = self.ki * self.integral;

        // Derivative term
        let derivative = (error - self.prev_error) / dt;
        let d_term = self.kd * derivative;

        self.prev_error = error;

        // Calculate total output
        let output = p_term + i_term + d_term;

        // Limit output
        output.clamp(-self.output_limit, self.output_limit)
    }

    /// Reset controller state
    pub fn reset(&mut self) {
        self.integral = 0.0;
        self.prev_error = 0.0;
    }

    /// Set gains
    pub fn set_gains(&mut self, kp: f32, ki: f32, kd: f32) {
        self.kp = kp;
        self.ki = ki;
        self.kd = kd;
    }

    /// Get current gains
    pub fn gains(&self) -> (f32, f32, f32) {
        (self.kp, self.ki, self.kd)
    }
}

impl Default for PidController {
    fn default() -> Self {
        Self::new(1.0, 0.0, 0.0, 1.0)
    }
}
