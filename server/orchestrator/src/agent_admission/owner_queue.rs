use std::collections::{HashMap, HashSet, VecDeque};

use crate::agent_work::{AgentWorkRequest, WorkOwner};

#[derive(Debug, Default)]
pub(super) struct OwnerFairQueue {
    owners: VecDeque<WorkOwner>,
    by_owner: HashMap<WorkOwner, VecDeque<String>>,
}

impl OwnerFairQueue {
    pub(super) fn push(&mut self, request: &AgentWorkRequest) {
        let owner = request.owner().clone();
        let queue = self.by_owner.entry(owner.clone()).or_insert_with(|| {
            self.owners.push_back(owner);
            VecDeque::new()
        });
        queue.push_back(request.request_id().to_owned());
    }

    pub(super) fn pop_dispatchable(
        &mut self,
        active_owners: &HashSet<WorkOwner>,
    ) -> Option<String> {
        let attempts = self.owners.len();
        for _ in 0..attempts {
            let owner = self.owners.pop_front()?;
            if active_owners.contains(&owner) {
                self.owners.push_back(owner);
                continue;
            }
            let (request_id, has_more) = {
                let queue = self.by_owner.get_mut(&owner)?;
                let request_id = queue.pop_front()?;
                (request_id, !queue.is_empty())
            };
            if has_more {
                self.owners.push_back(owner);
            } else {
                self.by_owner.remove(&owner);
            }
            return Some(request_id);
        }
        None
    }

    pub(super) fn remove(&mut self, owner: &WorkOwner, request_id: &str) {
        let mut remove_owner = false;
        if let Some(queue) = self.by_owner.get_mut(owner) {
            queue.retain(|queued| queued != request_id);
            remove_owner = queue.is_empty();
        }
        if remove_owner {
            self.by_owner.remove(owner);
            self.owners.retain(|queued_owner| queued_owner != owner);
        }
    }
}
