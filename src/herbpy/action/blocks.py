import logging, numpy, openravepy, prpy
from prpy.action import ActionMethod
from prpy.planning.base import PlanningError
from prpy.util import ComputeEnabledAABB

logger = logging.getLogger('herbpy')

@ActionMethod
def GrabBlock(robot, block, table, manip=None, preshape=[1.7, 1.7, 0.2, 2.45],
              **kw_args):
    """
    @param robot The robot performing the grasp
    @param block The block to grab
    @param table The table, or object, the block is resting on
    @param manip The manipulator to use to grab the block
      (if None active manipulator is used)
    """
    if manip is None:
        manip = robot.GetActiveManipulator()
    
    # First move the hand to the right preshape
    manip.hand.MoveHand(*preshape)

    # Get a tsr to move near the block
    block_tsr_list = robot.tsrlibrary(block, 'grasp', manip=manip)
    
    # Plan to a pose above the block
    with prpy.viz.RenderTSRList(block_tsr_list, robot.GetEnv()):
        with prpy.rave.Disabled(table, padding_only=True):
            manip.PlanToTSR(block_tsr_list)

    # Move down until touching the table
    try:
        with prpy.rave.Disabled(table, padding_only=True):
            table_aabb = ComputeEnabledAABB(table)
            table_height = table_aabb.pos()[2] + table_aabb.extents()[2]
            current_finger_height = manip.GetEndEffectorTransform()[2,3] - 0.14 # distance from finger tip to end-effector frame
            min_distance = current_finger_height - table_height
            print min_distance
        with prpy.rave.Disabled(table):
            with prpy.rave.Disabled(block):
                manip.MoveUntilTouch(direction=[0, 0, -1], distance=min_distance,
                                          timelimit=5)

                # Now move the hand parallel to the table to funnel the block into the fingers
                funnel_direction = -1.0*manip.GetEndEffectorTransform()[:3,0] #Negative x direction of end-effector
                funnel_direction[2] = 0.0 # project onto xy plane
                with prpy.viz.RenderVector(manip.GetEndEffectorTransform()[:3,3], funnel_direction, 0.1, robot.GetEnv()):
                    manip.PlanToEndEffectorOffset(direction=funnel_direction, distance=0.04, max_distance=0.1, timelimit=5)
        
        # Close the finger to grab the block
        manip.hand.MoveHand(f3=1.7)
            
        # Compute the pose of the block in the hand frame
        local_p = [0.01, 0, 0.24, 1.0]
        hand_pose = manip.GetEndEffectorTransform()
        world_p = numpy.dot(hand_pose, local_p)
        block_pose = block.GetTransform()
        block_pose[:,3] = world_p
        block_relative = numpy.dot(numpy.linalg.inv(hand_pose), block_pose)
        
        # Now lift the block up off the table
        with prpy.rave.Disabled(table):
            with prpy.rave.Disabled(block):
                manip.PlanToEndEffectorOffset(direction=[0, 0, 1], distance=0.05, timelimit=5)
            
        # OpenRAVE trick to hallucinate the block into the correct pose relative to the hand
        hand_pose = manip.GetEndEffectorTransform()
        block_pose = numpy.dot(hand_pose, block_relative)
        block.SetTransform(block_pose)
        manip.GetRobot().Grab(block)

    except PlanningError, e:
        logger.error('Failed to complete block grasp')
        raise

@ActionMethod
def PlaceBlock(robot, block, on_obj, center=True, manip=None, **kw_args):
    """
    Place a block on an object
    """

    # Get a tsr for this position
    object_place_list = robot.tsrlibrary(on_obj, 'point_on', manip=manip)
    place_tsr_list = robot.tsrlibrary(block, 'place_on', 
                                      pose_tsr_chain=object_place_list[0], 
                                      manip=manip)

    # Plan there
    with prpy.viz.RenderTSRList(place_tsr_list, robot.GetEnv()):
        manip.PlanToTSR(place_tsr_list)

    # Open the hand and drop the block
    manip.hand.MoveHand(f3=0.2)
    manip.GetRobot().Release(block)

    # Move the block down until it hits something
    block_pose = block.GetTransform()
    env = robot.GetEnv()
    while not env.CheckCollision(block) and block_pose[2,3] > 0.0:
        block_pose[2,3] -= 0.02
        block.SetTransform(block_pose)
    
    