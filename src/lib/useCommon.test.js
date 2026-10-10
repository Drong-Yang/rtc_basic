import React from 'react';
import { createRoot } from 'react-dom/client';
import { act } from 'react-dom/test-utils';
import { Provider } from 'react-redux';
import VERTC from '@volcengine/rtc';
import { Modal } from '@arco-design/web-react';
import store from '@/store';
import { localLeaveRoom, updateLocalUser } from '@/store/slices/room';
import RtcClient from './RtcClient';
import { useJoin } from './useCommon';

jest.mock('@volcengine/rtc', () => ({
  __esModule: true, default: { isSupported: jest.fn(async () => true) },
  MediaType: { AUDIO: 1 }, NetworkQuality: { UNKNOWN: 0 },
}));
jest.mock('@arco-design/web-react', () => ({ Modal: { error: jest.fn() }, Message: { error: jest.fn() } }));
jest.mock('./listenerHooks', () => () => ({}));
jest.mock('./RtcClient', () => ({
  __esModule: true, default: {
    basicInfo: { room_id: 'test-room', user_id: 'test-user' },
    createEngine: jest.fn(), addEventListeners: jest.fn(), joinRoom: jest.fn(),
    getDevices: jest.fn(), startAudioCapture: jest.fn(), publishStream: jest.fn(),
    startAgent: jest.fn(), leaveRoom: jest.fn(),
  },
}));

let root, container, join;
function Harness() { [, join] = useJoin(); return null; }
beforeEach(async () => {
  jest.clearAllMocks();
  VERTC.isSupported.mockResolvedValue(true);
  store.dispatch(localLeaveRoom());
  RtcClient.getDevices.mockReset().mockResolvedValue({ audioInputs: [{ deviceId: 'default' }], videoInputs: [] });
  RtcClient.startAudioCapture.mockReset().mockResolvedValue({});
  RtcClient.publishStream.mockReset().mockResolvedValue();
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => { root.render(<Provider store={store}><Harness /></Provider>); });
});
afterEach(async () => { await act(async () => { root.unmount(); }); container.remove(); });

test('waits for capture and publication before starting the AI', async () => {
  const steps = [];
  let releasePublish, markPublishing;
  const publishing = new Promise(resolve => { markPublishing = resolve; });
  const published = new Promise(resolve => { releasePublish = resolve; });
  RtcClient.startAudioCapture.mockImplementation(async () => { steps.push('capture'); });
  RtcClient.publishStream.mockImplementation(async () => { steps.push('publish'); markPublishing(); await published; });
  RtcClient.startAgent.mockImplementation(async () => { steps.push('agent'); });
  await act(async () => {
    const call = join();
    await publishing;
    expect(RtcClient.startAgent).not.toHaveBeenCalled();
    releasePublish();
    await call;
  });
  expect(steps).toEqual(['capture', 'publish', 'agent']);
  expect(store.getState().room.localUser.publishAudio).toBe(true);
});

test('capture failure aborts the call instead of playing a misleading welcome', async () => {
  RtcClient.startAudioCapture.mockRejectedValue(new Error('Microphone is busy'));
  await act(async () => { await join(); });
  expect(RtcClient.startAgent).not.toHaveBeenCalled();
  expect(RtcClient.publishStream).not.toHaveBeenCalled();
  expect(RtcClient.leaveRoom).toHaveBeenCalled();
  expect(store.getState().room.isJoined).toBe(false);
  expect(Modal.error).toHaveBeenCalledWith(expect.objectContaining({ content: 'Microphone is busy' }));
});

test('failed audio publication cannot produce a successful call', async () => {
  RtcClient.publishStream.mockRejectedValue(new Error('publish failed'));
  await act(async () => { await join(); });
  expect(RtcClient.startAgent).not.toHaveBeenCalled();
  expect(RtcClient.startAudioCapture).toHaveBeenCalled();
  expect(store.getState().room.localUser.publishAudio).toBe(false);
});

test('missing microphone permission stops before capture and assistant startup', async () => {
  RtcClient.getDevices.mockRejectedValue(new Error('Microphone permission denied'));
  await act(async () => { await join(); });
  expect(RtcClient.startAudioCapture).not.toHaveBeenCalled();
  expect(RtcClient.startAgent).not.toHaveBeenCalled();
  expect(Modal.error).toHaveBeenCalledWith(expect.objectContaining({ content: 'Microphone permission denied' }));
});

test('a new call explicitly enables capture even if a previous render held stale microphone state', async () => {
  await act(async () => { store.dispatch(updateLocalUser({ publishAudio: true })); });
  await act(async () => { await join(); });
  expect(RtcClient.startAudioCapture).toHaveBeenCalledTimes(1);
  expect(RtcClient.publishStream).toHaveBeenCalledTimes(1);
});
