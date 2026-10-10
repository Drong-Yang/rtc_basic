/**
 * Copyright 2025 Beijing Volcano Engine Technology Co., Ltd. All Rights Reserved.
 * SPDX-license-identifier: BSD-3-Clause
 */

import VERTC from '@volcengine/rtc';
import { Tooltip, Typography } from '@arco-design/web-react';
import { useSelector } from 'react-redux';
import { RootState } from '@/store';
import Operation from './components/Operation';
import CameraArea from '../MainArea/Room/CameraArea';
import { isMobile } from '@/utils/utils';
import { useScene } from '@/lib/useCommon';
import packageJson from '../../../../package.json';
import styles from './index.module.less';

function Menu() {
  const room = useSelector((state: RootState) => state.room);
  const isJoined = room?.isJoined;
  const { isVision, name } = useScene();
  const requestId = sessionStorage.getItem('RequestID');

  return (
    <div className={styles.wrapper}>
      {isJoined && isMobile() && isVision ? (
        <div className={styles['mobile-camera-wrapper']}>
          <CameraArea className={styles['mobile-camera']} />
        </div>
      ) : null}
      <div className={`${styles.box} ${styles.info}`}>
        <div className={styles.title}>AI 人设：{name}</div>
        <div className={styles.desc}>商品与价格均为虚构演示数据</div>
        <div className={styles.desc}>可咨询商品参数、购物与售后规则</div>
        <div className={styles.desc}>试着问：SC-PB27 多重？</div>
        <div className={styles.desc}>也可以问：七天无理由怎么退？</div>
        <div className={styles.desc}>说话即可打断；暂不支持订单查询或代办退款</div>
      </div>
      {isJoined ? <Operation /> : ''}
      {isJoined && (
        <div className={`${styles.box} ${styles.info}`} aria-label="语音输入状态">
          <div className={styles.title}>语音输入状态</div>
          <div className={styles.desc}>麦克风：{room.localUser.publishAudio ? '已开启' : '已静音'}</div>
          <div className={styles.desc}>输入音量：{room.localUser.audioPropertiesInfo?.linearVolume ?? '等待采集报告'}</div>
          <div className={styles.desc}>音频上行：{room.localUser.audioStats?.sendKBitrate ?? '等待统计'} kbps</div>
          <meter min={0} max={255} value={room.localUser.audioPropertiesInfo?.linearVolume ?? 0} aria-label="麦克风输入音量" />
          <div className={styles.desc}>说话时音量应变化；若一直为 0，请在麦克风设置中更换输入设备。</div>
          {room.voiceError && <div role="alert" style={{ color: '#b42318' }}>{room.voiceError}</div>}
        </div>
      )}
      <div className={`${styles.box} ${styles.info}`}>
        <div className={styles.title}>{isJoined ? '其他信息' : '版本信息'}</div>
        <div className={styles.desc}>Demo Version {packageJson.version}</div>
        <div className={styles.desc}>SDK Version {VERTC.getSdkVersion()}</div>
        {isJoined ? (
          <div className={styles.desc}>
            房间ID{' '}
            <Tooltip content={room.roomId || '-'}>
              <Typography.Paragraph
                ellipsis={{
                  rows: 1,
                  expandable: false,
                }}
                className={styles.value}
              >
                {room.roomId || '-'}
              </Typography.Paragraph>
            </Tooltip>
          </div>
        ) : (
          ''
        )}
        {room.isAIGCEnable ? (
          <div className={styles.desc}>
            RequestID{' '}
            <Tooltip content={requestId || '-'}>
              <Typography.Paragraph
                ellipsis={{
                  rows: 1,
                  expandable: false,
                }}
                className={styles.value}
              >
                {requestId || '-'}
              </Typography.Paragraph>
            </Tooltip>
          </div>
        ) : (
          ''
        )}
      </div>
    </div>
  );
}

export default Menu;
