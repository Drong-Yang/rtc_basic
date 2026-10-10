/**
 * Copyright 2025 Beijing Volcano Engine Technology Co., Ltd. All Rights Reserved.
 * SPDX-license-identifier: BSD-3-Clause
 */

import { useDispatch, useSelector } from 'react-redux';
import { RootState } from '@/store';
import CheckScene from './CheckScene';
import { SceneConfig, updateScene } from '@/store/slices/room';
import { useScene } from '@/lib/useCommon';
import style from './index.module.less';

function AIChangeCard() {
  const { scene, sceneConfigMap } = useSelector((state: RootState) => state.room);
  const dispatch = useDispatch();
  const { icon } = useScene();
  const Scenes = Object.keys(sceneConfigMap).map(key => sceneConfigMap[key]);

  const handleChecked = (checkedScene: string) => {
    dispatch(updateScene(checkedScene));
  };

  return (
    <div className={style.card}>
      <div className={style.avatar}>
        <img id="avatar-card" src={icon} alt="Avatar" />
      </div>
      <div className={style.title}>
        <div>欢迎咨询星核数码购物助手</div>
        <div className={style.desc}>
          商品与价格为虚构演示数据，可问参数和售后规则
        </div>
      </div>
      <div className={style.sceneContainer}>
        {Scenes.map((key: SceneConfig) =>
          <CheckScene
            key={key.name}
            icon={key.icon}
            title={key.name}
            checked={key.id === scene}
            onClick={() => handleChecked(key.id)}
          />
        )}
      </div>
    </div>
  );
}

export default AIChangeCard;
