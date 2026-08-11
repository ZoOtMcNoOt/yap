use crate::agent_work::{ExecutionRoute, SchedulingClass};

const RAPID_PRIORITY: [SchedulingClass; 13] = [
    SchedulingClass::Hot,
    SchedulingClass::Hot,
    SchedulingClass::Hot,
    SchedulingClass::Hot,
    SchedulingClass::Hot,
    SchedulingClass::Hot,
    SchedulingClass::Hot,
    SchedulingClass::Hot,
    SchedulingClass::Interactive,
    SchedulingClass::Interactive,
    SchedulingClass::Interactive,
    SchedulingClass::Interactive,
    SchedulingClass::BackgroundLlm,
];
const COMPLEX_PRIORITY: [SchedulingClass; 5] = [
    SchedulingClass::Interactive,
    SchedulingClass::Interactive,
    SchedulingClass::Interactive,
    SchedulingClass::Interactive,
    SchedulingClass::BackgroundLlm,
];
const SERVER_IO_PRIORITY: [SchedulingClass; 5] = [
    SchedulingClass::Interactive,
    SchedulingClass::Interactive,
    SchedulingClass::Interactive,
    SchedulingClass::Interactive,
    SchedulingClass::BackgroundIo,
];

pub(super) fn priority_schedule(route: ExecutionRoute) -> &'static [SchedulingClass] {
    match route {
        ExecutionRoute::RapidAutomation => &RAPID_PRIORITY,
        ExecutionRoute::ComplexOrchestration => &COMPLEX_PRIORITY,
        ExecutionRoute::ServerIo => &SERVER_IO_PRIORITY,
    }
}
