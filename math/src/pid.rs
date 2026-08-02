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

#[cfg(test)]
mod tests {
    use super::*;
    const EPS: f32 = 1e-5;

    fn approx_eq(a: f32, b: f32) -> bool {
        (a - b).abs() < EPS
    }

    #[test]
    fn proportional_only_output_scales_with_kp() {
        let mut pid = PidController::new(2.0, 0.0, 0.0, 100.0);
        let output = pid.update(3.0, 0.01);
        assert!(approx_eq(output, 6.0), "output: {output}");
    }

    #[test]
    fn integral_term_accumulates_error_over_time() {
        let mut pid = PidController::new(0.0, 1.0, 0.0, 100.0);
        // integral = sum(error*dt); constant error=2.0, dt=0.1, 5 steps -> integral=1.0
        let mut output = 0.0;
        for _ in 0..5 {
            output = pid.update(2.0, 0.1);
        }
        assert!(approx_eq(output, 1.0), "output: {output}");
    }

    #[test]
    fn integral_term_is_clamped_by_the_anti_windup_limit() {
        // integral_limit = output_limit * 0.5 = 5.0, so integral itself
        // saturates at 5.0 regardless of how much longer error is applied,
        // and ki=1.0 makes i_term read the clamped integral directly.
        let mut pid = PidController::new(0.0, 1.0, 0.0, 10.0);
        let mut output = 0.0;
        for _ in 0..20 {
            output = pid.update(1.0, 1.0);
        }
        assert!(approx_eq(output, 5.0), "output: {output}");
    }

    #[test]
    fn derivative_term_reacts_to_the_change_in_error_between_updates() {
        let mut pid = PidController::new(0.0, 0.0, 1.0, 100.0);
        pid.update(1.0, 0.1); // establishes prev_error = 1.0, output ~ 1.0/0.1 = 10 (first step, prev_error starts at 0)
        let output = pid.update(3.0, 0.1); // derivative = (3.0-1.0)/0.1 = 20.0
        assert!(approx_eq(output, 20.0), "output: {output}");
    }

    #[test]
    fn output_is_clamped_to_the_configured_limit() {
        let mut pid = PidController::new(10.0, 0.0, 0.0, 2.0);
        let output = pid.update(100.0, 0.01);
        assert!(approx_eq(output, 2.0), "output: {output}");

        let output_neg = pid.update(-100.0, 0.01);
        assert!(approx_eq(output_neg, -2.0), "output_neg: {output_neg}");
    }

    #[test]
    fn reset_clears_integral_and_derivative_history() {
        let mut pid = PidController::new(0.0, 1.0, 1.0, 100.0);
        pid.update(5.0, 0.1);
        pid.update(5.0, 0.1);
        pid.reset();

        // With integral and prev_error both cleared, a fresh update(0.0, ...)
        // should produce exactly zero output (p=0, i=0, d=(0-0)/dt=0).
        let output = pid.update(0.0, 0.1);
        assert_eq!(output, 0.0);
    }

    #[test]
    fn set_gains_replaces_kp_ki_kd_without_touching_integrator_state() {
        let mut pid = PidController::new(1.0, 1.0, 1.0, 100.0);
        pid.update(2.0, 0.1); // integral becomes nonzero: 0.2

        pid.set_gains(0.0, 2.0, 0.0);
        assert_eq!(pid.gains(), (0.0, 2.0, 0.0));

        // i_term = ki * integral = 2.0 * 0.2 = 0.4 (integral survived the gain change)
        let output = pid.update(0.0, 0.1);
        assert!(approx_eq(output, 0.4), "output: {output}");
    }

    #[test]
    fn gains_returns_the_constructed_kp_ki_kd() {
        let pid = PidController::new(1.5, 0.25, 0.75, 10.0);
        assert_eq!(pid.gains(), (1.5, 0.25, 0.75));
    }

    #[test]
    fn default_is_kp_1_with_zero_ki_kd_and_unit_output_limit() {
        let mut pid = PidController::default();
        assert_eq!(pid.gains(), (1.0, 0.0, 0.0));
        // output_limit=1.0: a large error should saturate at exactly 1.0.
        let output = pid.update(1000.0, 0.01);
        assert!(approx_eq(output, 1.0), "output: {output}");
    }
}
