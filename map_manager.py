
import rclpy

from datetime import datetime
from pathlib import Path
from threading import Event, Lock

from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor

from std_srvs.srv import Trigger
from nav2_msgs.srv import SaveMap

class MapManager(Node):

    def __init__(self):
        super().__init__('xuegecar_map_manager')

        # 地图保存目录和地图话题
        self.declare_parameter('save_dir', '/home/chuyun/maps')
        self.declare_parameter('map_topic', '/map')

        # 允许服务响应和客户端响应并发处理
        self.callback_group = ReentrantCallbackGroup()
        self.save_lock = Lock()

        # Nav2 Map Saver 客户端
        self.map_saver_client = self.create_client(
            SaveMap,
            '/map_saver/save_map',
            callback_group=self.callback_group
        )

        # 向 Qt 提供统一的保存服务
        self.save_service = self.create_service(
            Trigger,
            '/xuegecar/save_map',
            self.save_map_callback,
            callback_group=self.callback_group
        )

        self.get_logger().info(
            'MapManager started. Service: /xuegecar/save_map'
        )

    def save_map_callback(self, request, response):

        # 禁止两个保存任务同时运行
        if not self.save_lock.acquire(blocking=False):
            response.success = False
            response.message = 'A map save is already running'
            return response

        try:
            # 检查 Map Saver 服务
            if not self.map_saver_client.service_is_ready():
                response.success = False
                response.message = 'Map Saver service is unavailable'
                return response

            save_dir = Path(
                self.get_parameter('save_dir').value
            ).expanduser()

            map_topic = self.get_parameter('map_topic').value

            save_dir.mkdir(parents=True, exist_ok=True)

            # 自动生成不会覆盖旧文件的地图名称
            timestamp = datetime.now().strftime(
                '%Y%m%d_%H%M%S_%f'
            )

            map_name = 'map_' + timestamp
            map_prefix = str(save_dir / map_name)

            # 构造 Nav2 保存地图请求
            save_request = SaveMap.Request()

            save_request.map_topic = map_topic
            save_request.map_url = map_prefix
            save_request.image_format = 'pgm'
            save_request.map_mode = 'trinary'
            save_request.free_thresh = 0.25
            save_request.occupied_thresh = 0.65

            self.get_logger().info(
                f'Saving map to: {map_prefix}'
            )

            # 异步调用底层服务
            future = self.map_saver_client.call_async(
                save_request
            )

            finished = Event()
            future.add_done_callback(
                lambda _: finished.set()
            )

            # 最长等待 30 秒
            if not finished.wait(timeout=30.0):
                response.success = False
                response.message = 'Map save request timed out'
                return response

            result = future.result()

            yaml_path = Path(map_prefix + '.yaml')
            image_path = Path(map_prefix + '.pgm')

            if (
                result is not None
                and result.result
                and yaml_path.is_file()
                and image_path.is_file()
            ):
                response.success = True
                response.message = str(yaml_path)

                self.get_logger().info(
                    f'Map saved successfully: {yaml_path}'
                )
            else:
                response.success = False
                response.message = 'Map saving failed'

            return response

        except Exception as exc:
            self.get_logger().error(str(exc))
            response.success = False
            response.message = str(exc)
            return response

        finally:
            self.save_lock.release()

def main(args=None):
    rclpy.init(args=args)

    node = MapManager()

    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)

    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()