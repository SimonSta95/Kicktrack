#[macro_export]
macro_rules! kt_debug {
    ($($arg:tt)*) => {{
        #[cfg(debug_assertions)]
        {
            eprintln!($($arg)*);
        }
    }};
}
