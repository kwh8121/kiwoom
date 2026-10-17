-- LOCAL DEVELOPMENT ONLY. Never apply this seed to a hosted database.
-- Production provisioning must supply a separate secret outside source control.
alter role kiwoom_worker with login password 'kiwoom-worker-local';
